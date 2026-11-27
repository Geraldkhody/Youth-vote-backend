"""Tests for app/services/hubtel_fulfilment.py.

Like tests/test_transactions.py, this runs against a REAL MariaDB/MySQL
database (the same dedicated "youth_vote_test" schema), not the SQLite
used by most of the suite -- the concurrency tests here need genuine row
locking, which SQLite can't meaningfully provide.

Every Hubtel HTTP call (check_transaction_status, the final callback
POST) is mocked in every test in this file. None of them makes a real
network call.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import functools
import pytest
from sqlalchemy import create_engine, text

from app import create_app
from app.extensions import db
from app.models.admin_user import AdminUser
from app.models.category import Category
from app.models.nominee import Nominee
from app.models.transaction import Transaction
from app.models.vote import Vote
from app.models.voting_settings import get_settings
from app.providers.hubtel import HubtelError
from app.services.hubtel_fulfilment import (
    MAX_CALLBACK_ATTEMPTS,
    handle_fulfilment_request,
    process_hubtel_payment,
    send_final_callback,
)
from app.services.transactions import create_pending_transaction, record_successful_payment

TEST_DB_NAME = "youth_vote_test"
TEST_DB_URI = f"mysql+pymysql://root:@127.0.0.1:3306/{TEST_DB_NAME}?charset=utf8mb4"

# Naive (no tzinfo) on purpose -- matches how VotingSettings' dates come
# back after a real database round-trip (see app/services/voting_settings.py).
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
        # Explicit, not inherited from .env -- these tests mock
        # check_transaction_status/requests.post directly and assert on
        # those mocks, which only happens in "live" mode.
        "HUBTEL_MODE": "live",
        "HUBTEL_CALLBACK_ENABLED": True,
        "HUBTEL_FINAL_CALLBACK_URL": "https://gs-callback.hubtel.com:9055/callback",
        "HUBTEL_API_ID": "fake-id", "HUBTEL_API_SECRET": "super-secret-value",
        "HUBTEL_COLLECTION_ACCOUNT": "ACC1",
        # MySQL's default REPEATABLE READ can let a pooled connection keep
        # an old snapshot across requests (this test file mixes direct
        # ORM commits with HTTP requests through the test client, on a
        # real, persistent database -- unlike the rest of the suite's
        # SQLite). READ COMMITTED makes every query see the latest
        # committed data, which is what every test here assumes.
        "SQLALCHEMY_ENGINE_OPTIONS": {"isolation_level": "READ COMMITTED"},
    })

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user(app):
    with app.app_context():
        admin = AdminUser(name="Admin", email="admin@example.com", is_active=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()
        return admin.id


@pytest.fixture
def logged_in_client(client, admin_user):
    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "secret123"})
    token = response.get_json()["token"]
    auth_header = {"Authorization": f"Bearer {token}"}
    for method in ("get", "post", "patch", "put", "delete"):
        setattr(client, method, functools.partial(getattr(client, method), headers=auth_header))
    return client


@pytest.fixture
def nominee_id(app):
    with app.app_context():
        category = Category(name="Youth Leader of the Year", code_letter="A", is_active=True)
        db.session.add(category)
        db.session.commit()

        nominee = Nominee(
            category_id=category.id, code="A47", full_name="Ama Owusu",
            phone="233241234567", is_active=True,
        )
        db.session.add(nominee)
        db.session.commit()
        return nominee.id


def _open_voting(fee_pesewas=100):
    """Call from inside an app context."""
    settings = get_settings()
    settings.voting_opens_at = NOW - timedelta(days=1)
    settings.voting_closes_at = NOW + timedelta(days=1)
    settings.voting_paused = False
    settings.vote_fee_pesewas = fee_pesewas
    db.session.commit()


def _make_pending_transaction(nominee_id_, session_id, quantity=2):
    return create_pending_transaction(
        nominee_id=nominee_id_, phone="233241234567", quantity=quantity,
        channel="ussd", hubtel_session_id=session_id, now=NOW,
    )


def _paid_status_json(amount_pesewas):
    return {"Status": "Paid", "Amount": str(Decimal(amount_pesewas) / 100)}


# ---------------------------------------------------------------------
# process_hubtel_payment: paid / failed / inconclusive
# ---------------------------------------------------------------------

def test_valid_paid_amount_creates_vote_and_sends_callback_once(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-paid-ok")
        transaction_id = transaction.id

        mock_response = MagicMock(status_code=200)
        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, _paid_status_json(transaction.amount_pesewas))), \
             patch("app.services.hubtel_fulfilment.requests.post", return_value=mock_response) as mock_post:

            handle_fulfilment_request({"SessionId": "sess-paid-ok", "OrderId": "ORDER-1"})

            assert mock_post.call_count == 1
            sent_body = mock_post.call_args.kwargs["json"]
            assert sent_body == {
                "SessionId": "sess-paid-ok", "OrderId": "ORDER-1",
                "ServiceStatus": "success", "MetaData": None,
            }

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "success"
        assert t.callback_sent_at is not None
        votes = Vote.query.filter_by(transaction_id=transaction_id).all()
        assert len(votes) == 1
        assert votes[0].quantity == transaction.quantity


def test_same_fulfilment_request_twice_creates_one_vote_and_one_callback(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-twice")
        transaction_id = transaction.id
        body = {"SessionId": "sess-twice", "OrderId": "ORDER-1"}

        mock_response = MagicMock(status_code=200)
        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, _paid_status_json(transaction.amount_pesewas))), \
             patch("app.services.hubtel_fulfilment.requests.post", return_value=mock_response) as mock_post:

            handle_fulfilment_request(body)
            handle_fulfilment_request(body)

            assert mock_post.call_count == 1

        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 1


def test_wrong_amount_creates_no_vote_sets_needs_review_sends_no_callback(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-wrong-amount")
        transaction_id = transaction.id
        wrong_amount = transaction.amount_pesewas + 1

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, _paid_status_json(wrong_amount))), \
             patch("app.services.hubtel_fulfilment.requests.post") as mock_post:

            handle_fulfilment_request({"SessionId": "sess-wrong-amount", "OrderId": "ORDER-1"})

            assert not mock_post.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "pending"
        assert t.needs_review is True
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 0


def test_mocked_failed_status_marks_failed_no_vote_no_callback(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-failed")
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "Failed"})), \
             patch("app.services.hubtel_fulfilment.requests.post") as mock_post:

            process_hubtel_payment(transaction_id)

            assert not mock_post.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "failed"
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 0


@pytest.mark.parametrize("mock_kwargs", [
    {"return_value": (200, {"Status": "Pending"})},
    {"return_value": (200, {"Status": "SomethingWeird"})},
    {"side_effect": HubtelError("timed out")},
    {"side_effect": HubtelError("Hubtel's status-check API returned HTTP 500")},
])
def test_inconclusive_status_changes_nothing(app, nominee_id, mock_kwargs):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-inconclusive")
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.check_transaction_status", **mock_kwargs), \
             patch("app.services.hubtel_fulfilment.requests.post") as mock_post:
            process_hubtel_payment(transaction_id)
            assert not mock_post.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "pending"
        assert t.needs_review is False
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 0


@pytest.mark.parametrize("status_word", ["Unpaid", "unpaid"])
def test_unpaid_status_creates_no_vote_no_failure_stays_pending(app, nominee_id, status_word):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-unpaid")
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": status_word})), \
             patch("app.services.hubtel_fulfilment.requests.post") as mock_post:
            process_hubtel_payment(transaction_id)
            assert not mock_post.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "pending"
        assert t.needs_review is False
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 0

        # The sweep checks it again on a later run -- nothing about this
        # outcome stops that.
        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "Paid", "Amount": str(Decimal(transaction.amount_pesewas) / 100)})) as mock_check, \
             patch("app.services.hubtel_fulfilment.requests.post", return_value=MagicMock(status_code=200)):
            t.created_at = _real_now() - timedelta(minutes=10)
            t.last_status_check_at = _real_now() - timedelta(minutes=10)
            db.session.commit()
            app.test_cli_runner().invoke(args=["hubtel-sweep"])
            assert mock_check.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "success"


def test_refunded_with_no_vote_sets_needs_review_no_callback(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-refunded-novote")
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "Refunded"})), \
             patch("app.services.hubtel_fulfilment.requests.post") as mock_post:
            process_hubtel_payment(transaction_id)
            assert not mock_post.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "pending"
        assert t.needs_review is True
        assert t.review_reason == "refunded by Hubtel"
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 0


def test_refunded_after_vote_leaves_vote_untouched_sets_needs_review(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-refunded-postvote")
        record_successful_payment(transaction.id, paid_amount_pesewas=transaction.amount_pesewas, now=NOW)
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "Refunded"})), \
             patch("app.services.hubtel_fulfilment.requests.post") as mock_post:
            process_hubtel_payment(transaction_id)
            assert not mock_post.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "success"
        assert t.needs_review is True
        assert t.review_reason == "refunded after vote was recorded"
        assert t.callback_sent_at is None
        votes = Vote.query.filter_by(transaction_id=transaction_id).all()
        assert len(votes) == 1
        assert votes[0].quantity == transaction.quantity

        # Even if something later tries to send the callback, needs_review
        # blocks it.
        t.hubtel_order_id = "ORDER-1"
        db.session.commit()
        with patch("app.services.hubtel_fulfilment.requests.post", return_value=MagicMock(status_code=200)) as mock_post:
            send_final_callback(transaction_id)
            assert not mock_post.called
        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.callback_sent_at is None


def test_unknown_status_word_changes_nothing(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-unknown-word")
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "SomeBrandNewWord"})), \
             patch("app.services.hubtel_fulfilment.requests.post") as mock_post:
            process_hubtel_payment(transaction_id)
            assert not mock_post.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "pending"
        assert t.needs_review is False
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 0


def test_payment_confirmed_after_voting_closed_still_counts(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-closed-after")
        transaction_id = transaction.id
        amount = transaction.amount_pesewas

        settings = get_settings()
        settings.voting_closes_at = NOW + timedelta(minutes=1)
        db.session.commit()

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, _paid_status_json(amount))), \
             patch("app.services.hubtel_fulfilment.requests.post", return_value=MagicMock(status_code=200)):
            process_hubtel_payment(transaction_id)

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.status == "success"
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 1


# ---------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------

def test_concurrent_fulfilment_requests_create_one_vote_and_one_callback(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-concurrent-fulfil")
        transaction_id = transaction.id
        amount = transaction.amount_pesewas

    barrier = threading.Barrier(2)
    errors = []
    mock_post = MagicMock(return_value=MagicMock(status_code=200))

    def worker():
        try:
            barrier.wait(timeout=5)
            with app.app_context():
                handle_fulfilment_request({"SessionId": "sess-concurrent-fulfil", "OrderId": "ORDER-X"})
        except Exception as error:
            errors.append(error)

    with patch("app.services.hubtel_fulfilment.check_transaction_status",
               return_value=(200, _paid_status_json(amount))), \
         patch("app.services.hubtel_fulfilment.requests.post", mock_post):
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert errors == []
    assert mock_post.call_count == 1

    with app.app_context():
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 1


def test_two_overlapping_callback_attempts_send_only_one(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-overlap-callback")
        record_successful_payment(transaction.id, paid_amount_pesewas=transaction.amount_pesewas, now=NOW)
        t = Transaction.query.filter_by(id=transaction.id).first()
        t.hubtel_order_id = "ORDER-1"
        db.session.commit()
        transaction_id = transaction.id

    barrier = threading.Barrier(2)
    errors = []
    mock_post = MagicMock(return_value=MagicMock(status_code=200))

    def worker():
        try:
            barrier.wait(timeout=5)
            with app.app_context():
                send_final_callback(transaction_id)
        except Exception as error:
            errors.append(error)

    with patch("app.services.hubtel_fulfilment.requests.post", mock_post):
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert errors == []
    assert mock_post.call_count == 1

    with app.app_context():
        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.callback_sent_at is not None


# ---------------------------------------------------------------------
# Callback failure / retry / cap / disabled
# ---------------------------------------------------------------------

def test_callback_failure_keeps_vote_increments_attempts_saves_safe_error(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-callback-fails")
        record_successful_payment(transaction.id, paid_amount_pesewas=transaction.amount_pesewas, now=NOW)
        t = Transaction.query.filter_by(id=transaction.id).first()
        t.hubtel_order_id = "ORDER-1"
        db.session.commit()
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.requests.post", side_effect=Exception("boom with a secret")):
            send_final_callback(transaction_id)

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.callback_sent_at is None
        assert t.callback_attempts == 1
        assert t.callback_last_error is not None
        assert "boom with a secret" not in t.callback_last_error  # safe message only
        # The vote is untouched by a callback failure.
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 1


def test_callback_stops_retrying_after_max_attempts(app, nominee_id):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-retry-cap")
        record_successful_payment(transaction.id, paid_amount_pesewas=transaction.amount_pesewas, now=NOW)
        t = Transaction.query.filter_by(id=transaction.id).first()
        t.hubtel_order_id = "ORDER-1"
        db.session.commit()
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.requests.post", side_effect=Exception("down")):
            for _ in range(MAX_CALLBACK_ATTEMPTS):
                t = Transaction.query.filter_by(id=transaction_id).first()
                t.callback_last_attempt_at = NOW - timedelta(minutes=5)  # bypass the retry cooldown
                db.session.commit()
                send_final_callback(transaction_id)

            t = Transaction.query.filter_by(id=transaction_id).first()
            assert t.callback_attempts == MAX_CALLBACK_ATTEMPTS

            # One more: even bypassing the cooldown, the attempt cap refuses the claim.
            t.callback_last_attempt_at = NOW - timedelta(minutes=5)
            db.session.commit()
            send_final_callback(transaction_id)

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.callback_attempts == MAX_CALLBACK_ATTEMPTS


def test_callback_retries_fast_then_slow_then_gives_up_after_55_minutes(app, nominee_id):
    """Uses a controllable clock (the `now` kwarg), never real sleeping."""
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-callback-schedule")
        record_successful_payment(transaction.id, paid_amount_pesewas=transaction.amount_pesewas, now=NOW)
        t = Transaction.query.filter_by(id=transaction.id).first()
        t.hubtel_order_id = "ORDER-1"
        t.fulfilment_received_at = NOW
        db.session.commit()
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.requests.post", side_effect=Exception("still down")):
            # Within the first 10 minutes: every call is retried, even
            # just a minute after the last attempt (no cooldown applies).
            send_final_callback(transaction_id, now=NOW + timedelta(minutes=2))
            t = Transaction.query.filter_by(id=transaction_id).first()
            assert t.callback_attempts == 1

            send_final_callback(transaction_id, now=NOW + timedelta(minutes=3))
            t = Transaction.query.filter_by(id=transaction_id).first()
            assert t.callback_attempts == 2

            send_final_callback(transaction_id, now=NOW + timedelta(minutes=9))
            t = Transaction.query.filter_by(id=transaction_id).first()
            assert t.callback_attempts == 3

            # Past the 10-minute fast window, only 2 minutes after the
            # last attempt (minute 9): NOT retried yet -- needs 5 minutes.
            send_final_callback(transaction_id, now=NOW + timedelta(minutes=11))
            t = Transaction.query.filter_by(id=transaction_id).first()
            assert t.callback_attempts == 3

            # 6 minutes after that last attempt: retried again.
            send_final_callback(transaction_id, now=NOW + timedelta(minutes=15))
            t = Transaction.query.filter_by(id=transaction_id).first()
            assert t.callback_attempts == 4

        # Past the 55-minute mark: stop retrying, flag for review instead.
        with patch("app.services.hubtel_fulfilment.requests.post") as mock_post:
            send_final_callback(transaction_id, now=NOW + timedelta(minutes=56))
            assert not mock_post.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.callback_sent_at is None
        assert t.needs_review is True
        assert t.review_reason == "final callback not sent within one hour"
        # The vote itself is completely unaffected.
        assert Vote.query.filter_by(transaction_id=transaction_id).count() == 1


def test_callback_disabled_sends_nothing(nominee_id):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": TEST_DB_URI,
        "TESTING": True,
        "HUBTEL_MODE": "live",
        "HUBTEL_CALLBACK_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        try:
            _open_voting()
            transaction = _make_pending_transaction(nominee_id, "sess-callback-disabled")
            record_successful_payment(transaction.id, paid_amount_pesewas=transaction.amount_pesewas, now=NOW)
            t = Transaction.query.filter_by(id=transaction.id).first()
            t.hubtel_order_id = "ORDER-1"
            db.session.commit()

            with patch("app.services.hubtel_fulfilment.requests.post") as mock_post:
                send_final_callback(transaction.id)
                assert not mock_post.called

            t = Transaction.query.filter_by(id=transaction.id).first()
            assert t.callback_sent_at is None
        finally:
            db.session.remove()
            db.drop_all()


# ---------------------------------------------------------------------
# Sweep (flask hubtel-sweep)
# ---------------------------------------------------------------------

def _real_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_sweep_checks_old_enough_pending_but_not_too_recent(app, nominee_id):
    with app.app_context():
        _open_voting()
        real_now = _real_now()

        old_enough = _make_pending_transaction(nominee_id, "sess-old-enough")
        old_enough.created_at = real_now - timedelta(minutes=6)
        db.session.commit()

        too_recent = _make_pending_transaction(nominee_id, "sess-too-recent")
        too_recent.created_at = real_now - timedelta(minutes=2)
        db.session.commit()

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "Pending"})) as mock_check:
            app.test_cli_runner().invoke(args=["hubtel-sweep"])

        checked_refs = [call.args[0] for call in mock_check.call_args_list]
        assert "sess-old-enough" in checked_refs
        assert "sess-too-recent" not in checked_refs


def test_sweep_marks_very_old_pending_as_needs_review(app, nominee_id):
    with app.app_context():
        _open_voting()
        real_now = _real_now()

        stale = _make_pending_transaction(nominee_id, "sess-stale")
        stale.created_at = real_now - timedelta(hours=25)
        db.session.commit()
        stale_id = stale.id

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "Pending"})):
            app.test_cli_runner().invoke(args=["hubtel-sweep"])

        t = Transaction.query.filter_by(id=stale_id).first()
        assert t.needs_review is True
        assert t.review_reason == "no final status after 24 hours"
        assert t.status == "pending"
        assert Vote.query.filter_by(transaction_id=stale_id).count() == 0


def test_sweep_retries_pending_with_fulfilment_received_every_run(app, nominee_id):
    """A transaction whose fulfilment we've received 1 minute ago is
    still checked on this run -- the normal "5 minutes old" backstop rule
    doesn't apply once we know fulfilment has happened."""
    with app.app_context():
        _open_voting()
        real_now = _real_now()

        transaction = _make_pending_transaction(nominee_id, "sess-fulfilled-recent")
        transaction.created_at = real_now - timedelta(minutes=1)
        transaction.fulfilment_received_at = real_now - timedelta(minutes=1)
        db.session.commit()

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "Pending"})) as mock_check:
            app.test_cli_runner().invoke(args=["hubtel-sweep"])

        checked_refs = [call.args[0] for call in mock_check.call_args_list]
        assert "sess-fulfilled-recent" in checked_refs


def test_sweep_retries_a_failed_callback(app, nominee_id):
    with app.app_context():
        _open_voting()
        real_now = _real_now()

        transaction = _make_pending_transaction(nominee_id, "sess-sweep-retry")
        record_successful_payment(transaction.id, paid_amount_pesewas=transaction.amount_pesewas, now=NOW)
        t = Transaction.query.filter_by(id=transaction.id).first()
        t.hubtel_order_id = "ORDER-1"
        t.callback_attempts = 1
        t.callback_last_attempt_at = real_now - timedelta(minutes=10)
        db.session.commit()
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.requests.post",
                   return_value=MagicMock(status_code=200)) as mock_post:
            app.test_cli_runner().invoke(args=["hubtel-sweep"])
            assert mock_post.called

        t = Transaction.query.filter_by(id=transaction_id).first()
        assert t.callback_sent_at is not None


# ---------------------------------------------------------------------
# Admin transactions list
# ---------------------------------------------------------------------

def test_admin_transactions_list_requires_login(client):
    response = client.get("/api/admin/transactions")
    assert response.status_code == 401


def test_admin_transactions_list_minutes_since_fulfilment_and_callback_overdue(app, logged_in_client, nominee_id):
    with app.app_context():
        _open_voting()
        real_now = _real_now()

        overdue = _make_pending_transaction(nominee_id, "sess-overdue")
        record_successful_payment(overdue.id, paid_amount_pesewas=overdue.amount_pesewas, now=NOW)
        overdue_row = Transaction.query.filter_by(id=overdue.id).first()
        overdue_row.fulfilment_received_at = real_now - timedelta(minutes=45)
        overdue_reference = overdue_row.reference
        db.session.commit()

        not_overdue = _make_pending_transaction(nominee_id, "sess-not-overdue")
        record_successful_payment(not_overdue.id, paid_amount_pesewas=not_overdue.amount_pesewas, now=NOW)
        not_overdue_row = Transaction.query.filter_by(id=not_overdue.id).first()
        not_overdue_row.fulfilment_received_at = real_now - timedelta(minutes=5)
        not_overdue_reference = not_overdue_row.reference
        db.session.commit()

    response = logged_in_client.get("/api/admin/transactions")
    rows = {row["reference"]: row for row in response.get_json()}
    assert rows[overdue_reference]["minutes_since_fulfilment"] >= 45
    assert rows[not_overdue_reference]["minutes_since_fulfilment"] in (4, 5)

    overdue_response = logged_in_client.get("/api/admin/transactions?callback_overdue=1")
    overdue_refs = [row["reference"] for row in overdue_response.get_json()]
    assert overdue_reference in overdue_refs
    assert not_overdue_reference not in overdue_refs


def test_admin_transactions_list_masks_phone(app, logged_in_client, nominee_id):
    with app.app_context():
        _open_voting()
        _make_pending_transaction(nominee_id, "sess-admin-list", quantity=3)

    response = logged_in_client.get("/api/admin/transactions")
    assert response.status_code == 200
    rows = response.get_json()
    assert len(rows) == 1
    assert rows[0]["phone"] == "*********567"
    assert "233241234567" not in str(rows[0])
    assert rows[0]["nominee_code"] == "A47"
    assert rows[0]["quantity"] == 3


# ---------------------------------------------------------------------
# Secrets / production guard
# ---------------------------------------------------------------------

def test_secrets_never_appear_in_process_hubtel_payment_logs(app, nominee_id, caplog):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-secret-check")
        transaction_id = transaction.id

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   side_effect=HubtelError("Hubtel's status-check API returned HTTP 500")):
            with caplog.at_level(logging.WARNING):
                process_hubtel_payment(transaction_id)

        assert "super-secret-value" not in caplog.text


def test_fake_mode_refuses_to_start_in_production():
    with pytest.raises(RuntimeError):
        create_app({
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "TESTING": True,
            "HUBTEL_MODE": "fake",
            "APP_ENV": "production",
        })
