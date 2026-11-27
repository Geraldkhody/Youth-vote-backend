"""Tests for app/services/ussd.py -- the USSD menu.

These call handle_interaction() directly (not through HTTP) so each test
can inspect the resulting UssdSession/Transaction rows directly. The
route-level wiring (token check, request log, phone masking) is covered
separately in tests/test_hubtel.py.
"""

from datetime import datetime, timedelta

import pytest

import pathlib

from app.extensions import db
from app.models.category import Category
from app.models.nominee import Nominee
from app.models.transaction import Transaction
from app.models.voting_settings import get_settings
from app.services.ussd import handle_interaction
from app.services.ussd_text import is_gsm7

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
def eleven_long_categories(app):
    """11 active categories with long names (each with one nominee, so
    picking a category always reaches the nominee list), to exercise
    multi-page paging with continuous numbering."""
    with app.app_context():
        categories = [
            Category(
                name=f"Category Number {i:02d} For The Youth Awards Night",
                code_letter=chr(ord("A") + i), is_active=True,
            )
            for i in range(11)
        ]
        db.session.add_all(categories)
        db.session.commit()

        nominees = [
            Nominee(category_id=category.id, code=f"{category.code_letter}10",
                     full_name=f"Nominee For {category.code_letter}", phone="233241234567", is_active=True)
            for category in categories
        ]
        db.session.add_all(nominees)
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


@pytest.fixture
def category_with_thirty_nominees(app):
    """One category holding 30 active nominees with a long (60-char) name,
    to exercise nominee paging and name truncation."""
    with app.app_context():
        category = Category(name="Massive Category", code_letter="M", is_active=True)
        db.session.add(category)
        db.session.commit()

        long_name_tail = "x" * 54  # 6 + 54 = 60 chars total
        nominees = [
            Nominee(category_id=category.id, code=f"M{100 + i}", full_name=f"Nominee{i:02d}{long_name_tail}",
                    phone="233241234567", is_active=True)
            for i in range(30)
        ]
        db.session.add_all(nominees)
        db.session.commit()
        return category.id, [nominee.code for nominee in nominees]


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

        assert "1. Category A" in response["Message"]
        assert "5. Category E" in response["Message"]
        assert "0. More" in response["Message"]
        assert "00. Back" not in response["Message"]  # first page
        assert "Category F" not in response["Message"]
        assert "A - " not in response["Message"]  # no code letters in the category list
        assert len(response["Message"]) <= 160


def test_category_paging_second_page_has_remainder_no_more_has_back(app, many_categories):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)
        response = handle_interaction(_req("s1", "0"), now=NOW)

        assert "6. Category F" in response["Message"]
        assert "7. Category G" in response["Message"]
        assert "0. More" not in response["Message"]
        assert "00. Back" in response["Message"]
        assert len(response["Message"]) <= 160


def test_choosing_category_then_nominee_paging(app, category_with_many_nominees):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)  # choose a category
        response = handle_interaction(_req("s1", "1"), now=NOW)  # the only category

        assert "0. More" in response["Message"]
        assert "1. Nominee 0 - P10" in response["Message"]
        assert len(response["Message"]) <= 160

        response = handle_interaction(_req("s1", "0"), now=NOW)  # next nominee page
        assert "6. Nominee 5 - P15" in response["Message"]
        assert "0. More" not in response["Message"]
        assert "00. Back" in response["Message"]

        response = handle_interaction(_req("s1", "6"), now=NOW)  # pick item 6 (the first on this page)
        assert response["Type"] == "response"
        assert "Votes for" in response["Message"]
        assert "Nominee 5" in response["Message"]


def test_eleven_categories_all_shown_once_numbered_continuously_no_codes(app, eleven_long_categories):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        response = handle_interaction(_req("s1", "2"), now=NOW)

        seen_numbers = []
        for page in range(10):  # generous upper bound on page count
            for line in response["Message"].splitlines():
                if line[:1].isdigit() and ". " in line and not line.startswith("00."):
                    number = int(line.split(".", 1)[0])
                    if number != 0:  # "0. More" isn't an item row
                        seen_numbers.append(number)
            assert len(response["Message"]) <= 160
            for letter in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"]:
                assert f"{letter} - " not in response["Message"]
            if "0. More" not in response["Message"]:
                break
            response = handle_interaction(_req("s1", "0"), now=NOW)

        assert "0. More" not in response["Message"]
        assert seen_numbers == list(range(1, 12))


def test_choosing_number_on_second_page_selects_item_by_overall_position(app, eleven_long_categories):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        response = handle_interaction(_req("s1", "2"), now=NOW)  # page 1

        # Walk pages (via "0. More") until item #7 is shown on the current
        # page -- the exact page size varies with name length, so this
        # finds whichever page that lands on rather than assuming one.
        while "7. " not in response["Message"]:
            assert "0. More" in response["Message"]
            response = handle_interaction(_req("s1", "0"), now=NOW)

        response = handle_interaction(_req("s1", "7"), now=NOW)

        assert response["Type"] == "response"
        assert "Choose a nominee" in response["Message"]
        # The 7th category overall is category G (categories are ordered
        # by code_letter, A..K for this fixture) -- its one nominee (G10)
        # must be the one shown, proving #7 meant the 7th item overall,
        # not the 2nd item on whatever page it was shown on.
        assert "G10" in response["Message"]


def test_number_not_on_current_page_reasks_with_error(app, eleven_long_categories):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)  # page 1: items 1..N

        response = handle_interaction(_req("s1", "20"), now=NOW)  # far out of range

        assert response["Type"] == "response"
        assert "not valid" in response["Message"].lower()
        assert "1. " in response["Message"]


def test_thirty_nominees_paging_numbers_continuously_and_truncates_name_not_code(app, category_with_thirty_nominees):
    category_id, codes = category_with_thirty_nominees
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)
        response = handle_interaction(_req("s1", "1"), now=NOW)  # only category -> nominee list

        seen_codes = []
        for _ in range(15):  # generous upper bound on page count
            for line in response["Message"].splitlines():
                if line[:1].isdigit() and " - " in line and not line.startswith("00."):
                    code = line.rsplit(" - ", 1)[1]
                    assert code in codes  # the code itself is never truncated
                    seen_codes.append(code)
            assert len(response["Message"]) <= 160
            if "0. More" not in response["Message"]:
                break
            response = handle_interaction(_req("s1", "0"), now=NOW)

        assert "0. More" not in response["Message"]
        assert sorted(seen_codes) == sorted(codes)
        assert len(seen_codes) == len(set(seen_codes))


def test_back_returns_to_previous_page_with_varying_page_sizes(app, category_with_thirty_nominees):
    category_id, codes = category_with_thirty_nominees
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)
        page1 = handle_interaction(_req("s1", "1"), now=NOW)
        page2 = handle_interaction(_req("s1", "0"), now=NOW)

        assert page2["Message"] != page1["Message"]

        back_to_page1 = handle_interaction(_req("s1", " 00 "), now=NOW)  # spaces around "00"
        assert back_to_page1["Message"] == page1["Message"]
        assert "00. Back" not in back_to_page1["Message"]  # first page again


def test_cedi_symbol_never_appears_in_category_or_nominee_lists(app, eleven_long_categories, category_with_thirty_nominees):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        response = handle_interaction(_req("s1", "2"), now=NOW)
        assert "₵" not in response["Message"]


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

        assert "3 votes" in response["Message"]
        assert "GHS 4.50" in response["Message"]
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
        assert "GHS 6.00" in response["Message"]  # 2 * 3.00
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


@pytest.mark.parametrize("type_", ["Timeout", "timeout", "Release", "TIMEOUT"])
def test_timeout_and_release_types_end_session_no_transaction_case_insensitive(app, nominee_in_category, type_):
    with app.app_context():
        _open_voting()
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A47"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)
        response = handle_interaction(_req("s1", "", type_=type_), now=NOW)

        assert response["Type"] == "release"
        assert Transaction.query.count() == 0


def test_unknown_type_never_returns_500_ends_up_safe(app):
    with app.app_context():
        _open_voting()
        # No crash for a Type we've never seen, and no session exists yet
        # either -- falls back to showing the main menu rather than
        # raising.
        response = handle_interaction(_req("s-unknown-type", "", type_="SomeNewMobileAppEvent"), now=NOW)

        assert response["SessionId"] == "s-unknown-type"
        assert response["Label"]
        assert response["DataType"]
        assert response["FieldType"]
        assert response["Message"]


@pytest.mark.parametrize("platform", ["Webstore", "Hubtel-App", "USSD"])
def test_every_platform_gets_mandatory_response_fields(app, platform):
    with app.app_context():
        _open_voting()
        body = _req("s-platform", type_="initiation")
        body["Platform"] = platform
        response = handle_interaction(body, now=NOW)

        for field in ("SessionId", "Type", "Message", "Label", "DataType", "FieldType"):
            assert field in response
            assert response[field]


# ---------------------------------------------------------------------
# GSM7 safety (see app/services/ussd_text.py)
# ---------------------------------------------------------------------

# A nominee name combining everything to_gsm7 has to handle: the
# Ghanaian "open e" and "open o" letters, curly quotes, and an emoji.
GSM7_HOSTILE_NAME = "Ɛb’Ɔd’é “J” \U0001f600 Mensah"


@pytest.fixture
def nominee_with_hostile_name(app, two_categories):
    category_id, _ = two_categories
    with app.app_context():
        nominee = Nominee(
            category_id=category_id, code="A48", full_name=GSM7_HOSTILE_NAME,
            phone="233241234567", is_active=True,
        )
        db.session.add(nominee)
        db.session.commit()
        return nominee.id


def test_every_screen_in_a_full_flow_is_gsm7_safe_and_within_160_chars(app, nominee_with_hostile_name):
    with app.app_context():
        _open_voting(fee_pesewas=100)
        messages = []

        messages.append(handle_interaction(_req("s1", type_="initiation"), now=NOW)["Message"])
        messages.append(handle_interaction(_req("s1", "1"), now=NOW)["Message"])
        messages.append(handle_interaction(_req("s1", "A48"), now=NOW)["Message"])  # quantity screen
        messages.append(handle_interaction(_req("s1", "abc"), now=NOW)["Message"])  # invalid quantity
        messages.append(handle_interaction(_req("s1", "3"), now=NOW)["Message"])  # confirm screen
        messages.append(handle_interaction(_req("s1", "9"), now=NOW)["Message"])  # invalid confirm choice

        settings = get_settings()
        settings.vote_fee_pesewas = 300
        db.session.commit()
        messages.append(handle_interaction(_req("s1", "1"), now=NOW)["Message"])  # fee changed, re-asked

        final = handle_interaction(_req("s1", "1"), now=NOW)  # AddToCart
        messages.append(final["Message"])

        for message in messages:
            assert is_gsm7(message), message
            assert len(message) <= 160
            assert "₵" not in message


def test_confirm_screen_fits_long_name_and_huge_quantity(app, two_categories):
    category_id, _ = two_categories
    with app.app_context():
        nominee = Nominee(
            category_id=category_id, code="A49", full_name="X" * 60,
            phone="233241234567", is_active=True,
        )
        db.session.add(nominee)
        db.session.commit()

        _open_voting(fee_pesewas=100)
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A49"), now=NOW)
        response = handle_interaction(_req("s1", "1" * 9), now=NOW)  # a 9-digit quantity

        assert "1. Confirm" in response["Message"]
        assert "2. Cancel" in response["Message"]
        assert "A49" in response["Message"]
        assert len(response["Message"]) <= 160


def test_addtocart_message_label_and_item_name_are_gsm7_safe(app, nominee_with_hostile_name):
    with app.app_context():
        _open_voting(fee_pesewas=100)
        handle_interaction(_req("s1", type_="initiation"), now=NOW)
        handle_interaction(_req("s1", "1"), now=NOW)
        handle_interaction(_req("s1", "A48"), now=NOW)
        handle_interaction(_req("s1", "2"), now=NOW)
        response = handle_interaction(_req("s1", "1"), now=NOW)

        assert response["Type"] == "AddToCart"
        assert is_gsm7(response["Message"])
        assert is_gsm7(response["Label"])
        assert is_gsm7(response["Item"]["ItemName"])


def test_no_cedi_sign_literal_in_ussd_source_files():
    backend_dir = pathlib.Path(__file__).resolve().parent.parent
    for relative_path in ("app/services/ussd.py", "app/services/ussd_text.py"):
        source = (backend_dir / relative_path).read_text(encoding="utf-8")
        assert "₵" not in source, f"cedi sign literal found in {relative_path}"


def test_website_pricing_still_uses_cedi_sign():
    # format_cedis (the website/admin formatter) is untouched by the
    # USSD GSM7 fix -- it's allowed, and expected, to use the cedi sign.
    from app.services.pricing import format_cedis

    assert "₵" in format_cedis(100)
