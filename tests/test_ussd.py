"""Tests for app/services/ussd.py -- the USSD menu.

These call handle_interaction() directly (not through HTTP) so each test
can inspect the resulting UssdSession/Transaction rows directly. The
route-level wiring (token check, request log, phone masking) is covered
separately in tests/test_hubtel.py.
"""

from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models.category import Category
from app.models.nominee import Nominee
from app.models.transaction import Transaction
from app.models.voting_settings import get_settings
from app.services.ussd import handle_interaction

NOW = datetime(2026, 6, 1, 12, 0, 0)


def _req(session_id, message="", type_="response", mobile="233200585542"):
    return {
        "Type": type_,
        "Message": message,
        "ServiceCode": "920",
        "Operator": "mtn",
        "Mobile": mobile,
        "SessionId": session_id,
        "Sequence": 1,
        "Platform": "USSD",
    }


def _open_voting(fee_pesewas=None):
    """Call from inside an app context."""
    settings = get_settings()
    settings.voting_opens_at = NOW - timedelta(days=1)
    settings.voting_closes_at = NOW + timedelta(days=1)
    settings.voting_paused = False
    if fee_pesewas is not None:
        settings.vote_fee_pesewas = fee_pesewas
    db.session.commit()


@pytest.fixture
def two_categories(app):
    with app.app_context():
        cat_a = Category(name="Youth Leader of the Year", code_letter="A", is_active=True)
        cat_b = Category(name="Sports Star of the Year", code_letter="B", is_active=True)
        db.session.add_all([cat_a, cat_b])
        db.session.commit()
        return cat_a.id, cat_b.id


@pytest.fixture
def nominee_in_category(app, two_categories):
    category_id, _ = two_categories
    with app.app_context():
        nominee = Nominee(
            category_id=category_id, code="A47", full_name="Ama Owusu",
            phone="233241234567", is_active=True,
        )
        db.session.add(nominee)
        db.session.commit()
        return nominee.id


@pytest.fixture
def inactive_nominee_code(app, two_categories):
    category_id, _ = two_categories
    with app.app_context():
        nominee = Nominee(
            category_id=category_id, code="A50", full_name="Inactive Guy",
            phone="233241234567", is_active=False,
        )
        db.session.add(nominee)
        db.session.commit()
        return nominee.code


@pytest.fixture
def many_categories(app):
    """7 active categories -- A..G -- to exercise paging (5 per page)."""
    with app.app_context():
        categories = [
            Category(name=f"Category {chr(ord('A') + i)}", code_letter=chr(ord("A") + i), is_active=True)
            for i in range(7)
        ]
        db.session.add_all(categories)
        db.session.commit()
        return [category.id for category in categories]


@pytest.fixture
def category_with_many_nominees(app):
    """One category holding 7 active nominees, to exercise nominee paging."""
    with app.app_context():
        category = Category(name="Popular Category", code_letter="P", is_active=True)
        db.session.add(category)
        db.session.commit()

        nominees = [
            Nominee(category_id=category.id, code=f"P{10 + i}", full_name=f"Nominee {i}",
                    phone="233241234567", is_active=True)
            for i in range(7)
        ]
        db.session.add_all(nominees)
        db.session.commit()
        return category.id


# ---------------------------------------------------------------------
# Voting not open
# ---------------------------------------------------------------------

def test_initiation_when_not_scheduled_ends_session(app):
    with app.app_context():
        response = handle_interaction(_req("s1", type_="initiation"), now=NOW)
        assert response["Type"] == "release"
        assert "not" in response["Message"].lower()


def test_initiation_when_upcoming_shows_opening_date(app):
    with app.app_context():
        settings = get_settings()
        settings.voting_opens_at = NOW + timedelta(days=3)
        settings.voting_closes_at = NOW + timedelta(days=10)
        db.session.commit()

        response = handle_interaction(_req("s1", type_="initiation"), now=NOW)
        assert response["Type"] == "release"
        assert "opens" in response["Message"].lower()


def test_initiation_when_paused_ends_session(app):
    with app.app_context():
        settings = get_settings()
        settings.voting_opens_at = NOW - timedelta(days=1)
        settings.voting_closes_at = NOW + timedelta(days=1)
        settings.voting_paused = True
        db.session.commit()

        response = handle_interaction(_req("s1", type_="initiation"), now=NOW)
        assert response["Type"] == "release"
        assert "paused" in response["Message"].lower()


def test_initiation_when_closed_ends_session(app):
    with app.app_context():
        settings = get_settings()
        settings.voting_opens_at = NOW - timedelta(days=10)
        settings.voting_closes_at = NOW - timedelta(days=1)
        db.session.commit()

        response = handle_interaction(_req("s1", type_="initiation"), now=NOW)
        assert response["Type"] == "release"
        assert "closed" in response["Message"].lower()


# ---------------------------------------------------------------------
# Main menu / nominee code entry
# ---------------------------------------------------------------------

def test_main_menu_shown_when_voting_open(app):
    with app.app_context():
        _open_voting()
        response = handle_interaction(_req("s1", type_="initiation"), now=NOW)
        assert response["Type"] == "response"
        assert "1. Vote with a nominee code" in response["Message"]


def test_valid_nominee_code_proceeds_to_quantity(app, nominee_in_category):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        response = handle_interaction(_req("s1", "A47"), now=NOW)

        assert response["Type"] == "response"
        assert "Ama Owusu" in response["Message"]
        assert "A47" in response["Message"]


def test_lowercase_and_spaced_nominee_code_accepted(app, nominee_in_category):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        response = handle_interaction(_req("s1", " a 47 "), now=NOW)

        assert "Ama Owusu" in response["Message"]


def test_invalid_nominee_code_asks_again(app, nominee_in_category):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        response = handle_interaction(_req("s1", "Z99"), now=NOW)

        assert response["Type"] == "response"
        assert "not found" in response["Message"].lower()


def test_inactive_nominee_code_is_not_found(app, inactive_nominee_code):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        response = handle_interaction(_req("s1", inactive_nominee_code), now=NOW)

        assert "not found" in response["Message"].lower()


# ---------------------------------------------------------------------
# Category / nominee paging
# ---------------------------------------------------------------------

def test_category_paging_first_page_has_five_and_more(app, many_categories):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        response = handle_interaction(_req("s1", "2"), now=NOW)

        assert "1. A - Category A" in response["Message"]
        assert "5. E - Category E" in response["Message"]
        assert "0. More" in response["Message"]
        assert "Category F" not in response["Message"]
        assert len(response["Message"]) <= 160


def test_category_paging_second_page_has_remainder_no_more(app, many_categories):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)
        response = handle_interaction(_req("s1", "0"), now=NOW)

        assert "1. F - Category F" in response["Message"]
        assert "2. G - Category G" in response["Message"]
        assert "0. More" not in response["Message"]
        assert len(response["Message"]) <= 160


def test_choosing_category_then_nominee_paging(app, category_with_many_nominees):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)  # choose a category
        response = handle_interaction(_req("s1", "1"), now=NOW)  # the only category

        assert "0. More" in response["Message"]
        assert "Nominee 0" in response["Message"]
        assert len(response["Message"]) <= 160

        response = handle_interaction(_req("s1", "0"), now=NOW)  # next nominee page
        assert "Nominee 5" in response["Message"]
        assert "0. More" not in response["Message"]

        response = handle_interaction(_req("s1", "1"), now=NOW)  # pick first on this page
        assert response["Type"] == "response"
        assert "How many votes" in response["Message"]


# ---------------------------------------------------------------------
# Quantity validation
# ---------------------------------------------------------------------

@pytest.mark.parametrize("bad_input", ["0", "-1", "abc", "1.5", ""])
def test_invalid_quantity_reasks(app, nominee_in_category, bad_input):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)

        response = handle_interaction(_req("s1", bad_input), now=NOW)

        assert response["Type"] == "response"
        assert "whole number" in response["Message"].lower()


def test_huge_quantity_reasks_without_crashing(app, nominee_in_category):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)

        response = handle_interaction(_req("s1", str(2**70)), now=NOW)

        assert response["Type"] == "response"
        assert "too large" in response["Message"].lower()


# ---------------------------------------------------------------------
# Confirm screen / fee change
# ---------------------------------------------------------------------

def test_confirm_screen_shows_right_total(app, nominee_in_category):
    with app.app_context():
        _open_voting(fee_pesewas=150)
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)
        response = handle_interaction(_req("s1", "3"), now=NOW)

        assert "3 vote(s)" in response["Message"]
        assert "GH₵4.50" in response["Message"]
        assert "1. Confirm" in response["Message"]
        assert "2. Cancel" in response["Message"]


def test_fee_change_between_confirm_screen_and_confirm_reasks(app, nominee_in_category):
    with app.app_context():
        _open_voting(fee_pesewas=100)
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)  # quantity 2, fee 100 -> total 200

        settings = get_settings()
        settings.vote_fee_pesewas = 300
        db.session.commit()

        response = handle_interaction(_req("s1", "1"), now=NOW)  # confirm

        assert response["Type"] == "response"  # not AddToCart -- re-asked
        assert "fee has changed" in response["Message"].lower()
        assert "GH₵6.00" in response["Message"]  # 2 * 3.00
        assert Transaction.query.count() == 0


# ---------------------------------------------------------------------
# Confirm -> AddToCart
# ---------------------------------------------------------------------

def test_confirm_creates_pending_transaction_and_addtocart(app, nominee_in_category):
    with app.app_context():
        _open_voting(fee_pesewas=100)
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)
        handle_interaction(_req("s1", "5"), now=NOW)
        response = handle_interaction(_req("s1", "1"), now=NOW)

        assert response["Type"] == "AddToCart"
        assert response["SessionId"] == "s1"
        assert response["Label"] == response["Message"]
        assert response["DataType"] == "display"
        assert response["FieldType"] == "text"
        assert response["Item"]["ItemName"] == "5 votes A47"
        assert response["Item"]["Qty"] == 1
        assert response["Item"]["Price"] == 5.0

        transactions = Transaction.query.filter_by(hubtel_session_id="s1").all()
        assert len(transactions) == 1
        assert transactions[0].status == "pending"
        assert transactions[0].quantity == 5
        assert transactions[0].amount_pesewas == 500


def test_repeated_confirm_for_same_session_creates_no_second_transaction(app, nominee_in_category):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)
        first = handle_interaction(_req("s1", "1"), now=NOW)

        second = handle_interaction(_req("s1", "1"), now=NOW)  # Hubtel retries

        assert first["Type"] == second["Type"] == "AddToCart"
        assert first["Item"] == second["Item"]
        assert Transaction.query.filter_by(hubtel_session_id="s1").count() == 1


def test_no_transaction_before_confirm(app, nominee_in_category):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)  # reaches the confirm screen only

        assert Transaction.query.count() == 0


# ---------------------------------------------------------------------
# Cancel / release
# ---------------------------------------------------------------------

def test_cancel_at_confirm_creates_no_transaction(app, nominee_in_category):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)
        response = handle_interaction(_req("s1", "2"), now=NOW)  # cancel

        assert response["Type"] == "release"
        assert Transaction.query.count() == 0


def test_release_type_creates_no_transaction(app, nominee_in_category):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)
        response = handle_interaction(_req("s1", "", type_="release"), now=NOW)

        assert response["Type"] == "release"
        assert Transaction.query.count() == 0
