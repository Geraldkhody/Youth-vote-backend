"""Tests for scripts/explain_transaction.py.

Every Hubtel HTTP call is mocked -- none of these tests makes a real
network call. Uses an in-memory SQLite database (no row-locking needed
here, unlike tests/test_hubtel_fulfilment.py).
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.extensions import db
from app.models.category import Category
from app.models.nominee import Nominee
from app.models.transaction import Transaction
from app.models.vote import Vote
from app.models.voting_settings import get_settings
from app.services.transactions import create_pending_transaction
from scripts.explain_transaction import run

NOW = datetime(2026, 6, 1, 12, 0, 0)


@pytest.fixture
def app():
    test_app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "TESTING": True,
        "HUBTEL_MODE": "live",
        "HUBTEL_CALLBACK_ENABLED": True,
        "HUBTEL_API_ID": "fake-id", "HUBTEL_API_SECRET": "super-secret-value",
        "HUBTEL_COLLECTION_ACCOUNT": "ACC1",
    })
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


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
    settings = get_settings()
    settings.voting_opens_at = NOW - timedelta(days=1)
    settings.voting_closes_at = NOW + timedelta(days=1)
    settings.voting_paused = False
    settings.vote_fee_pesewas = fee_pesewas
    db.session.commit()


def _make_pending_transaction(nominee_id_, session_id, quantity=1):
    return create_pending_transaction(
        nominee_id=nominee_id_, phone="233241234567", quantity=quantity,
        channel="ussd", hubtel_session_id=session_id, now=NOW,
    )


def test_dry_run_makes_no_database_write(app, nominee_id, capsys):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-explain-dry")
        reference = transaction.reference

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "Paid", "Amount": "1.01", "AmountAfterCharges": "1.00"})):
            ok = run(app, reference, apply_changes=False)

        assert ok is True
        t = Transaction.query.filter_by(reference=reference).first()
        assert t.status == "pending"
        assert t.last_status_outcome is None
        assert t.last_status_check_at is None
        assert Vote.query.filter_by(transaction_id=t.id).count() == 0

    output = capsys.readouterr().out
    assert "Dry run only" in output
    assert "Resulting last_status_outcome: paid" in output
    assert "Create exactly one Vote" in output


def test_apply_actually_processes_the_transaction(app, nominee_id, capsys):
    with app.app_context():
        _open_voting()
        transaction = _make_pending_transaction(nominee_id, "sess-explain-apply")
        reference = transaction.reference
        # Needed for the real callback to go out -- send_final_callback
        # never claims a transaction with no hubtel_order_id yet.
        transaction.hubtel_order_id = "ORDER-1"
        db.session.commit()

        with patch("app.services.hubtel_fulfilment.check_transaction_status",
                   return_value=(200, {"Status": "Paid", "Amount": "1.01", "AmountAfterCharges": "1.00"})), \
             patch("app.services.hubtel_fulfilment.requests.post", return_value=MagicMock(status_code=200)) as mock_post:
            ok = run(app, reference, apply_changes=True)
            assert mock_post.called

        assert ok is True
        t = Transaction.query.filter_by(reference=reference).first()
        assert t.status == "success"
        assert t.last_status_outcome == "paid"
        assert Vote.query.filter_by(transaction_id=t.id).count() == 1

    output = capsys.readouterr().out
    assert "--apply given" in output


def test_refuses_to_run_with_fake_mode(nominee_id, capsys):
    fake_app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "TESTING": True,
        "HUBTEL_MODE": "fake",
    })
    with fake_app.app_context():
        db.create_all()
        try:
            ok = run(fake_app, "VSOMEREFERENCE1", apply_changes=False)
        finally:
            db.session.remove()
            db.drop_all()

    assert ok is False
    assert "Refusing to run" in capsys.readouterr().out


def test_unknown_reference_reports_not_found(app, capsys):
    with app.app_context():
        ok = run(app, "VDOESNOTEXIST1", apply_changes=False)

    assert ok is False
    assert "No transaction found" in capsys.readouterr().out
