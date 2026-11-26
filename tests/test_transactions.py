"""Tests for app/services/transactions.py.

These run against a REAL MariaDB/MySQL database (a dedicated
"youth_vote_test" schema on the same server as local dev), not the SQLite
used by the rest of the test suite. Two things here genuinely need that:

- SELECT ... FOR UPDATE row locking, which the concurrency test below
  relies on, and which SQLite doesn't meaningfully support (SQLite locks
  the whole database file, not a row, and this project's :memory: SQLite
  setup can't even share one database across threads).
- CHECK constraint enforcement, which SQLite historically treats more
  loosely than MariaDB/MySQL do.

This file defines its own `app` fixture (and its own small set of
category/nominee fixtures), which override the SQLite ones from
tests/conftest.py for every test in this file only.
"""

import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import create_app
from app.extensions import db
from app.models.category import Category
from app.models.nominee import Nominee
from app.models.transaction import Transaction
from app.models.vote import Vote
from app.models.voting_settings import get_settings
from app.services.transactions import (
    create_pending_transaction,
    get_nominee_vote_total,
    mark_payment_cancelled,
    mark_payment_failed,
    record_successful_payment,
)

TEST_DB_NAME = "youth_vote_test"
TEST_DB_URI = f"mysql+pymysql://root:@127.0.0.1:3306/{TEST_DB_NAME}?charset=utf8mb4"

# A fixed instant used everywhere below instead of the real current time,
# so every test is deterministic. Naive (no tzinfo) on purpose -- that's
# how VotingSettings' dates come back after a real database round-trip
# (see app/services/voting_settings.py), so every "now" passed around
# needs to be naive too, to compare on the same footing.
NOW = datetime(2026, 6, 1, 12, 0, 0)


def _ensure_test_database_exists():
    server_engine = create_engine("mysql+pymysql://root:@127.0.0.1:3306/?charset=utf8mb4")
    with server_engine.connect() as connection:
        connection.execute(text(
            f"CREATE DATABASE IF NOT EXISTS {TEST_DB_NAME} "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
    server_engine.dispose()


@pytest.fixture
def app():
    _ensure_test_database_exists()

    test_app = create_app({
        "SQLALCHEMY_DATABASE_URI": TEST_DB_URI,
        "TESTING": True,
    })

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def active_category(app):
    with app.app_context():
        category = Category(name="Youth Leader of the Year", code_letter="T", is_active=True)
        db.session.add(category)
        db.session.commit()
        return category.id


@pytest.fixture
def active_nominee(app, active_category):
    with app.app_context():
        nominee = Nominee(
            category_id=active_category, code="T10", full_name="Test Nominee",
            phone="233241234567", is_active=True,
        )
        db.session.add(nominee)
        db.session.commit()
        return nominee.id


@pytest.fixture
def inactive_nominee(app, active_category):
    with app.app_context():
        nominee = Nominee(
            category_id=active_category, code="T11", full_name="Inactive Nominee",
            phone="233241234568", is_active=False,
        )
        db.session.add(nominee)
        db.session.commit()
        return nominee.id


def _set_window(opens_at=None, closes_at=None, paused=False):
    """Set the voting window directly on the one VotingSettings row.
    Must be called from inside an app context."""
    settings = get_settings()
    settings.voting_opens_at = opens_at
    settings.voting_closes_at = closes_at
    settings.voting_paused = paused
    db.session.commit()


# ---------------------------------------------------------------------
# create_pending_transaction
# ---------------------------------------------------------------------

def test_stores_the_current_fee(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        settings = get_settings()
        settings.vote_fee_pesewas = 250
        db.session.commit()

        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=3, channel="web", now=NOW,
        )

        assert transaction.unit_fee_pesewas == 250
        assert transaction.amount_pesewas == 750


def test_refused_when_voting_not_scheduled(app, active_nominee):
    with app.app_context():
        _set_window(None, None)
        with pytest.raises(ValueError):
            create_pending_transaction(
                nominee_id=active_nominee, phone="233241234567", quantity=1, channel="web", now=NOW,
            )


def test_refused_when_voting_closed(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=2), NOW - timedelta(days=1))
        with pytest.raises(ValueError):
            create_pending_transaction(
                nominee_id=active_nominee, phone="233241234567", quantity=1, channel="web", now=NOW,
            )


def test_refused_when_voting_paused(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1), paused=True)
        with pytest.raises(ValueError):
            create_pending_transaction(
                nominee_id=active_nominee, phone="233241234567", quantity=1, channel="web", now=NOW,
            )


def test_refused_for_inactive_nominee(app, inactive_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        with pytest.raises(ValueError):
            create_pending_transaction(
                nominee_id=inactive_nominee, phone="233241234567", quantity=1, channel="web", now=NOW,
            )


def test_refused_for_missing_nominee(app):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        with pytest.raises(ValueError):
            create_pending_transaction(
                nominee_id=999999, phone="233241234567", quantity=1, channel="web", now=NOW,
            )


@pytest.mark.parametrize("quantity", [0, -1, 1.5])
def test_refused_for_invalid_quantity(app, active_nominee, quantity):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        with pytest.raises(ValueError):
            create_pending_transaction(
                nominee_id=active_nominee, phone="233241234567", quantity=quantity, channel="web", now=NOW,
            )


def test_large_quantity_has_no_artificial_maximum(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        # quantity is a 32-bit INT column (per spec), so that -- not the
        # 64-bit amount_pesewas column -- is the real ceiling. This just
        # needs to be far bigger than anyone would plausibly buy at once,
        # to prove there's no smaller, artificial cap in the service itself.
        quantity = 2_000_000

        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=quantity, channel="web", now=NOW,
        )

        assert transaction.quantity == quantity
        assert transaction.amount_pesewas == quantity * transaction.unit_fee_pesewas


def test_fee_change_after_creation_does_not_alter_stored_fee(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        settings = get_settings()
        settings.vote_fee_pesewas = 100
        db.session.commit()

        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=3, channel="web", now=NOW,
        )
        assert transaction.unit_fee_pesewas == 100
        assert transaction.amount_pesewas == 300

        settings.vote_fee_pesewas = 500  # change the fee AFTER the transaction exists
        db.session.commit()

        refreshed = Transaction.query.filter_by(id=transaction.id).first()
        assert refreshed.unit_fee_pesewas == 100
        assert refreshed.amount_pesewas == 300


# ---------------------------------------------------------------------
# record_successful_payment
# ---------------------------------------------------------------------

def test_successful_payment_creates_exactly_one_vote_with_right_quantity(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=5, channel="web", now=NOW,
        )

        confirmed = record_successful_payment(
            transaction.reference, paid_amount_pesewas=transaction.amount_pesewas, now=NOW,
        )

        assert confirmed.status == "success"
        assert confirmed.confirmed_at == NOW
        votes = Vote.query.filter_by(transaction_id=confirmed.id).all()
        assert len(votes) == 1
        assert votes[0].quantity == 5


def test_second_confirmation_creates_no_second_vote_and_changes_nothing(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=2, channel="web", now=NOW,
        )
        first = record_successful_payment(
            transaction.reference, paid_amount_pesewas=transaction.amount_pesewas, now=NOW,
        )

        second = record_successful_payment(
            transaction.reference, paid_amount_pesewas=transaction.amount_pesewas,
            now=NOW + timedelta(minutes=5),
        )

        votes = Vote.query.filter_by(transaction_id=transaction.id).all()
        assert len(votes) == 1
        assert second.status == "success"
        # confirmed_at is NOT bumped by the duplicate -- nothing changes.
        assert second.confirmed_at == first.confirmed_at == NOW


def test_wrong_amount_creates_no_vote_and_sets_needs_review(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=2, channel="web", now=NOW,
        )
        wrong_amount = transaction.amount_pesewas + 1

        updated = record_successful_payment(transaction.reference, paid_amount_pesewas=wrong_amount, now=NOW)

        assert updated.status == "pending"
        assert updated.needs_review is True
        assert "does not match" in updated.review_reason
        assert Vote.query.filter_by(transaction_id=transaction.id).first() is None


@pytest.mark.parametrize("initial_status", ["failed", "cancelled"])
def test_payment_on_failed_or_cancelled_transaction_creates_no_vote(app, active_nominee, initial_status):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=2, channel="web", now=NOW,
        )
        if initial_status == "failed":
            mark_payment_failed(transaction.reference, reason="test setup")
        else:
            mark_payment_cancelled(transaction.reference)

        updated = record_successful_payment(
            transaction.reference, paid_amount_pesewas=transaction.amount_pesewas, now=NOW,
        )

        assert updated.status == initial_status
        assert updated.needs_review is True
        assert Vote.query.filter_by(transaction_id=transaction.id).first() is None


def test_payment_after_voting_closed_still_counts(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=2), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=1, channel="web", now=NOW,
        )

        # Voting closes right after the transaction was created.
        _set_window(NOW - timedelta(days=2), NOW + timedelta(minutes=1))
        confirmation_time = NOW + timedelta(hours=1)  # after voting_closes_at

        confirmed = record_successful_payment(
            transaction.reference, paid_amount_pesewas=transaction.amount_pesewas, now=confirmation_time,
        )

        assert confirmed.status == "success"
        vote = Vote.query.filter_by(transaction_id=confirmed.id).first()
        assert vote is not None
        assert vote.quantity == 1


def test_concurrent_confirmations_create_exactly_one_vote(app, active_nominee):
    """Two real threads (each with its own app context, and so its own
    database connection) both try to confirm the same payment at
    essentially the same moment. The row lock inside
    record_successful_payment should serialize them -- whichever gets
    there first does the real work; the other sees 'success' already and
    no-ops. Either way, exactly one vote must exist afterwards."""
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=4, channel="web", now=NOW,
        )
        reference = transaction.reference
        amount = transaction.amount_pesewas
        transaction_id = transaction.id

    barrier = threading.Barrier(2)
    errors = []

    def worker():
        try:
            barrier.wait(timeout=5)
            with app.app_context():
                record_successful_payment(reference, paid_amount_pesewas=amount, now=NOW)
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == [], f"worker thread(s) raised: {errors}"

    with app.app_context():
        votes = Vote.query.filter_by(transaction_id=transaction_id).all()
        assert len(votes) == 1
        assert votes[0].quantity == 4

        refreshed = Transaction.query.filter_by(id=transaction_id).first()
        assert refreshed.status == "success"


# ---------------------------------------------------------------------
# mark_payment_failed / mark_payment_cancelled
# ---------------------------------------------------------------------

def test_mark_payment_failed_sets_status_and_reason(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=1, channel="web", now=NOW,
        )

        updated = mark_payment_failed(transaction.reference, reason="Hubtel reported failure")

        assert updated.status == "failed"
        assert updated.review_reason == "Hubtel reported failure"


def test_mark_payment_failed_never_changes_a_success_transaction(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=1, channel="web", now=NOW,
        )
        record_successful_payment(transaction.reference, paid_amount_pesewas=transaction.amount_pesewas, now=NOW)

        updated = mark_payment_failed(transaction.reference, reason="late failure report")

        assert updated.status == "success"


def test_mark_payment_cancelled_sets_status(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=1, channel="web", now=NOW,
        )

        updated = mark_payment_cancelled(transaction.reference)

        assert updated.status == "cancelled"


def test_mark_payment_cancelled_never_changes_a_success_transaction(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        transaction = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=1, channel="web", now=NOW,
        )
        record_successful_payment(transaction.reference, paid_amount_pesewas=transaction.amount_pesewas, now=NOW)

        updated = mark_payment_cancelled(transaction.reference)

        assert updated.status == "success"


# ---------------------------------------------------------------------
# Database constraints
# ---------------------------------------------------------------------

def test_check_constraint_rejects_amount_not_matching_quantity_times_fee(app, active_nominee):
    with app.app_context():
        bad_transaction = Transaction(
            reference="VBADAMOUNT001", channel="web", nominee_id=active_nominee,
            phone="233241234567", quantity=3, unit_fee_pesewas=100,
            amount_pesewas=250,  # should be 300
            status="pending",
        )
        db.session.add(bad_transaction)

        # MariaDB/MySQL (via PyMySQL) report a CHECK constraint violation
        # as OperationalError, not IntegrityError -- DBAPIError is the
        # shared parent of both, so this catches it either way.
        with pytest.raises(DBAPIError):
            db.session.commit()
        db.session.rollback()


def test_check_constraint_rejects_vote_quantity_zero(app, active_nominee):
    with app.app_context():
        transaction = Transaction(
            reference="VZEROQTYVOTE1", channel="web", nominee_id=active_nominee,
            phone="233241234567", quantity=2, unit_fee_pesewas=100, amount_pesewas=200,
            status="success",
        )
        db.session.add(transaction)
        db.session.commit()

        bad_vote = Vote(transaction_id=transaction.id, nominee_id=active_nominee, quantity=0)
        db.session.add(bad_vote)

        with pytest.raises(DBAPIError):
            db.session.commit()
        db.session.rollback()


def test_unique_constraint_rejects_second_vote_for_same_transaction(app, active_nominee):
    with app.app_context():
        transaction = Transaction(
            reference="VDOUBLEVOTE001", channel="web", nominee_id=active_nominee,
            phone="233241234567", quantity=2, unit_fee_pesewas=100, amount_pesewas=200,
            status="success",
        )
        db.session.add(transaction)
        db.session.commit()

        db.session.add(Vote(transaction_id=transaction.id, nominee_id=active_nominee, quantity=2))
        db.session.commit()

        db.session.add(Vote(transaction_id=transaction.id, nominee_id=active_nominee, quantity=2))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


# ---------------------------------------------------------------------
# get_nominee_vote_total
# ---------------------------------------------------------------------

def test_get_nominee_vote_total_sums_quantities(app, active_nominee):
    with app.app_context():
        _set_window(NOW - timedelta(days=1), NOW + timedelta(days=1))
        assert get_nominee_vote_total(active_nominee) == 0

        first = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=3, channel="web", now=NOW,
        )
        record_successful_payment(first.reference, paid_amount_pesewas=first.amount_pesewas, now=NOW)

        second = create_pending_transaction(
            nominee_id=active_nominee, phone="233241234567", quantity=7, channel="ussd",
            hubtel_session_id="sess-123", now=NOW,
        )
        record_successful_payment(second.reference, paid_amount_pesewas=second.amount_pesewas, now=NOW)

        assert get_nominee_vote_total(active_nominee) == 10
