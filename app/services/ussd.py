"""The USSD menu shown on Hubtel's Service Interaction URL.

This builds the JSON response for every step of: pick a nominee (by code,
or by browsing categories then nominees) -> enter a quantity -> confirm ->
AddToCart (handed off to Hubtel's checkout to actually take payment).

No transaction is created until the user confirms. Nothing here ever
raises for bad user input -- invalid input always re-shows the current
screen with a short error, never a crash (see handle_interaction).
"""

import re
from datetime import datetime, timezone

from app.extensions import db
from app.models.category import Category
from app.models.nominee import Nominee
from app.models.transaction import Transaction
from app.models.ussd_session import UssdSession
from app.models.voting_settings import get_settings
from app.services.pricing import calculate_vote_amount, pesewas_to_cedis
from app.services.transactions import create_pending_transaction
from app.services.ussd_text import USSD_MAX_CHARS, finalize_ussd_message, format_ghs, to_gsm7
from app.services.voting_status import is_voting_open, voting_state
from app.utils import normalize_phone

# Steps a USSD session can be in (UssdSession.step).
STEP_MAIN_MENU = "main_menu"
STEP_AWAITING_CODE = "awaiting_code"
STEP_CHOOSING_CATEGORY = "choosing_category"
STEP_CHOOSING_NOMINEE = "choosing_nominee"
STEP_AWAITING_QUANTITY = "awaiting_quantity"
STEP_CONFIRMING = "confirming"

PAGE_SIZE = 5
# VERIFY: Hubtel's real limit on AddToCart's Item.ItemName isn't captured
# (see docs/HUBTEL_USSD_NOTES.md) -- this is a conservative guess.
MAX_ITEM_NAME_LENGTH = 40

# Row-length caps for the category/nominee lists (see _truncate_name) --
# chosen so a single row never comes close to USSD_MAX_CHARS, even for a
# category/nominee with an unusually long name.
CATEGORY_NAME_MAX_LENGTH = 30
NOMINEE_NAME_MAX_LENGTH = 24

# The nominee name in the quantity/confirm screens shrinks to fit
# whatever's left after the fixed/required text, but never below this --
# see _fit_name_to_budget.
MIN_FITTED_NAME_LENGTH = 10

NOMINEE_CODE_PATTERN = re.compile(r"^[A-Z]{1,3}\d{2,3}$")


def _naive_utc_now():
    """Matches how VotingSettings' dates are stored (see
    app/services/voting_settings.py for why)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def handle_interaction(body, now=None):
    """Build the Hubtel response for one interaction request.

    Reads/writes UssdSession as a side effect, and -- only once the user
    confirms -- creates exactly one pending Transaction. Never raises for
    bad input; an unrecognised step or message re-shows the current
    screen (or restarts the menu) instead.
    """
    now = now if now is not None else _naive_utc_now()

    session_id = body.get("SessionId", "")
    raw_message = (body.get("Message") or "").strip()
    request_type = body.get("Type")
    phone = normalize_phone(body.get("Mobile")) or (body.get("Mobile") or "")

    if request_type == "release":
        # The user ended the session themselves -- no transaction, and
        # nothing left to remember.
        _delete_session(session_id)
        return _release(session_id, "Session ended.")

    # Hubtel can retry its own request for a session we already finished
    # (and cleaned up our side of). If we already created a pending
    # transaction for this exact session, resend the same AddToCart
    # instead of starting the menu over -- never create a second one.
    existing_transaction = Transaction.query.filter_by(
        hubtel_session_id=session_id, status="pending",
    ).first()
    if existing_transaction is not None:
        nominee = Nominee.query.get(existing_transaction.nominee_id)
        return _add_to_cart(session_id, existing_transaction, nominee)

    session_row = UssdSession.query.get(session_id)

    if request_type == "initiation" or session_row is None:
        session_row = session_row or UssdSession(
            session_id=session_id, phone=phone, step=STEP_MAIN_MENU, data={},
        )
        db.session.add(session_row)
        return _show_main_menu_or_closed_message(session_row, now)

    session_row.phone = phone or session_row.phone
    step = session_row.step

    if step == STEP_MAIN_MENU:
        return _handle_main_menu_choice(session_row, raw_message)
    if step == STEP_AWAITING_CODE:
        return _handle_code_entry(session_row, raw_message, now)
    if step == STEP_CHOOSING_CATEGORY:
        return _handle_category_choice(session_row, raw_message)
    if step == STEP_CHOOSING_NOMINEE:
        return _handle_nominee_choice(session_row, raw_message, now)
    if step == STEP_AWAITING_QUANTITY:
        return _handle_quantity_entry(session_row, raw_message, now)
    if step == STEP_CONFIRMING:
        return _handle_confirm_choice(session_row, raw_message, now)

    # Unknown/unexpected step -- never crash, just restart at the top.
    return _show_main_menu_or_closed_message(session_row, now)


# ---------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------

def _base_response(session_id, response_type, message, data_type, field_type):
    # Every screen goes through finalize_ussd_message here -- this is
    # the one place _ask and _release both funnel through, so no call
    # site can forget it (see app/services/ussd_text.py for why this
    # matters: a non-GSM7 character silently cuts the message to ~70
    # characters on the network, not 160).
    message = finalize_ussd_message(message)
    return {
        "SessionId": session_id,
        "Type": response_type,
        "Message": message,
        "Label": message,
        "DataType": data_type,
        "FieldType": field_type,
    }


def _ask(session_id, message, data_type="select", field_type="text"):
    """A "response" that keeps the session open, waiting for the user's
    next input."""
    return _base_response(session_id, "response", message, data_type, field_type)


def _release(session_id, message):
    """Ends the session with a final message -- no more input expected."""
    return _base_response(session_id, "release", message, "display", "text")


def _add_to_cart(session_id, transaction, nominee):
    item_name = to_gsm7(f"{transaction.quantity} votes {nominee.code}"[:MAX_ITEM_NAME_LENGTH])
    message = finalize_ussd_message("The request has been submitted. Please wait for a payment prompt soon")

    return {
        "SessionId": session_id,
        "Type": "AddToCart",
        "Message": message,
        "Item": {
            "ItemName": item_name,
            "Qty": 1,
            "Price": pesewas_to_cedis(transaction.amount_pesewas),
        },
        "Label": message,
        "DataType": "display",
        "FieldType": "text",
    }


# ---------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------

def _set_step(session_row, step, data=None):
    session_row.step = step
    session_row.data = data or {}


def _delete_session(session_id):
    UssdSession.query.filter_by(session_id=session_id).delete()
    db.session.commit()


# ---------------------------------------------------------------------
# Main menu / closed messages
# ---------------------------------------------------------------------

def _show_main_menu_or_closed_message(session_row, now):
    settings = get_settings()
    state = voting_state(settings, now)

    if state != "open":
        message = _closed_message(state, settings)
        _delete_session(session_row.session_id)
        return _release(session_row.session_id, message)

    _set_step(session_row, STEP_MAIN_MENU)
    db.session.commit()

    message = "Welcome to Youth Awards Voting\n1. Vote with a nominee code\n2. Choose a category"
    return _ask(session_row.session_id, message, data_type="select")


def _closed_message(state, settings):
    if state == "not_scheduled":
        return "Voting has not been scheduled yet. Please check back later."
    if state == "upcoming":
        opens = settings.voting_opens_at.strftime("%d %b %Y") if settings.voting_opens_at else "soon"
        return f"Voting opens {opens}. Please check back then."
    if state == "paused":
        return "Voting is temporarily paused. Please try again later."
    if state == "closed":
        return "Voting has closed. Thank you for your interest."
    return "Voting is not currently available."  # defensive default


def _handle_main_menu_choice(session_row, raw_message):
    choice = raw_message.strip()

    if choice == "1":
        _set_step(session_row, STEP_AWAITING_CODE)
        db.session.commit()
        return _ask(session_row.session_id, "Enter the nominee's code (e.g. B47):", data_type="input")

    if choice == "2":
        return _show_category_page(session_row, start_index=0)

    _set_step(session_row, STEP_MAIN_MENU)
    db.session.commit()
    return _ask(
        session_row.session_id,
        "Sorry, that's not valid.\n1. Vote with a nominee code\n2. Choose a category",
        data_type="select",
    )


# ---------------------------------------------------------------------
# Nominee code entry
# ---------------------------------------------------------------------

def _handle_code_entry(session_row, raw_message, now):
    nominee = _find_active_nominee_by_code(raw_message)

    if nominee is None:
        return _ask(
            session_row.session_id,
            "Nominee code not found. Enter the nominee's code (e.g. B47):",
            data_type="input",
        )

    return _show_quantity_prompt(session_row, nominee)


def _find_active_nominee_by_code(raw_code):
    # Accept lowercase and spaces (e.g. "b 47") -- strip all whitespace
    # and uppercase before matching.
    code = re.sub(r"\s+", "", raw_code or "").upper()
    if not NOMINEE_CODE_PATTERN.match(code):
        return None
    return Nominee.query.filter_by(code=code, is_active=True).first()


# ---------------------------------------------------------------------
# Browsing: categories, then nominees
# ---------------------------------------------------------------------

def _active_categories():
    return Category.query.filter_by(is_active=True).order_by(Category.code_letter).all()


def _active_nominees(category_id):
    return Nominee.query.filter_by(category_id=category_id, is_active=True).order_by(Nominee.code).all()


def _truncate_name(name, max_length):
    """Shorten name with "..." if it's over max_length, never returning
    more than max_length characters."""
    if len(name) <= max_length:
        return name
    return name[: max_length - 3] + "..."


def _category_line(category):
    # Code letters are deliberately left out -- voters pick by name only.
    return _truncate_name(category.name, CATEGORY_NAME_MAX_LENGTH)


def _nominee_line(nominee):
    # Name first, then the code -- and the code is never shortened.
    name = _truncate_name(nominee.full_name, NOMINEE_NAME_MAX_LENGTH)
    return f"{name} - {nominee.code}"


def _render_list_message(header, items, line_for, start_index, has_more, has_back):
    """Number each row by its position in the WHOLE list (start_index +
    offset + 1), not its position on this page, so numbering stays
    continuous across pages."""
    lines = [header]
    for offset, item in enumerate(items):
        number = start_index + offset + 1
        lines.append(f"{number}. {line_for(item)}")
    if has_more:
        lines.append("0. More")
    if has_back:
        lines.append("00. Back")
    return "\n".join(lines)


def _build_page_and_message(items, start_index, header, line_for, has_back):
    """Pick up to PAGE_SIZE items starting at start_index, but stop early
    (keeping at least one item) if adding another would push the message
    over USSD_MAX_CHARS -- "5 per page" is the normal case; a long list
    of long names falls back to fewer rows per page instead of a message
    Hubtel might reject or truncate.

    The navigation lines are reserved first: "00. Back" is included in
    every size check when has_back is true (it's already known from
    start_index alone), and "0. More" is assumed present while sizing
    rows -- the real has_more is only known afterwards, but dropping an
    unneeded "0. More" line can only make the final message shorter."""
    selected = []
    index = start_index

    while index < len(items) and len(selected) < PAGE_SIZE:
        candidate = selected + [items[index]]
        candidate_message = _render_list_message(
            header, candidate, line_for, start_index, has_more=True, has_back=has_back,
        )
        if len(candidate_message) > USSD_MAX_CHARS and selected:
            break
        selected = candidate
        index += 1

    has_more = index < len(items)
    message = _render_list_message(header, selected, line_for, start_index, has_more, has_back)
    return selected, has_more, index, message


def _show_category_page(session_row, start_index, history=None, error=False):
    history = history if history is not None else []
    categories = _active_categories()
    header = "Sorry, that's not valid.\nChoose a category:" if error else "Choose a category:"
    has_back = start_index > 0
    selected, has_more, next_index, message = _build_page_and_message(
        categories, start_index, header, _category_line, has_back,
    )

    if not selected:
        return _show_main_menu_or_closed_message(session_row, _naive_utc_now())

    _set_step(session_row, STEP_CHOOSING_CATEGORY, {
        "category_ids": [category.id for category in selected],
        "start_index": start_index,
        "next_index": next_index,
        "has_more": has_more,
        "has_back": has_back,
        "history": history,
    })
    db.session.commit()
    return _ask(session_row.session_id, message, data_type="select")


def _handle_category_choice(session_row, raw_message):
    data = session_row.data or {}
    category_ids = data.get("category_ids", [])
    has_more = data.get("has_more", False)
    has_back = data.get("has_back", False)
    next_index = data.get("next_index", 0)
    start_index = data.get("start_index", 0)
    history = data.get("history", [])
    choice = raw_message.strip()

    if choice == "0" and has_more:
        return _show_category_page(session_row, start_index=next_index, history=history + [start_index])

    if choice == "00" and has_back:
        previous_start = history[-1] if history else 0
        return _show_category_page(session_row, start_index=previous_start, history=history[:-1])

    if choice not in ("0", "00") and choice.isdigit():
        position = int(choice) - start_index
        if 1 <= position <= len(category_ids):
            category_id = category_ids[position - 1]
            return _show_nominee_page(session_row, category_id, start_index=0, history=[])

    return _show_category_page(session_row, start_index=start_index, history=history, error=True)


def _show_nominee_page(session_row, category_id, start_index, history=None, error=False):
    history = history if history is not None else []
    nominees = _active_nominees(category_id)
    header = "Sorry, that's not valid.\nChoose a nominee:" if error else "Choose a nominee:"
    has_back = start_index > 0
    selected, has_more, next_index, message = _build_page_and_message(
        nominees, start_index, header, _nominee_line, has_back,
    )

    if not selected:
        # No active nominees in this category -- go back to the category list.
        return _show_category_page(session_row, start_index=0, history=[])

    _set_step(session_row, STEP_CHOOSING_NOMINEE, {
        "category_id": category_id,
        "nominee_ids": [nominee.id for nominee in selected],
        "start_index": start_index,
        "next_index": next_index,
        "has_more": has_more,
        "has_back": has_back,
        "history": history,
    })
    db.session.commit()
    return _ask(session_row.session_id, message, data_type="select")


def _handle_nominee_choice(session_row, raw_message, now):
    data = session_row.data or {}
    nominee_ids = data.get("nominee_ids", [])
    has_more = data.get("has_more", False)
    has_back = data.get("has_back", False)
    next_index = data.get("next_index", 0)
    start_index = data.get("start_index", 0)
    category_id = data.get("category_id")
    history = data.get("history", [])
    choice = raw_message.strip()

    if choice == "0" and has_more:
        return _show_nominee_page(session_row, category_id, start_index=next_index, history=history + [start_index])

    if choice == "00" and has_back:
        previous_start = history[-1] if history else 0
        return _show_nominee_page(session_row, category_id, start_index=previous_start, history=history[:-1])

    if choice not in ("0", "00") and choice.isdigit():
        position = int(choice) - start_index
        if 1 <= position <= len(nominee_ids):
            nominee_id = nominee_ids[position - 1]
            nominee = Nominee.query.filter_by(id=nominee_id, is_active=True).first()
            if nominee is None:
                # Went inactive between listing and choosing -- treat it
                # like an invalid choice rather than crash.
                return _show_nominee_page(session_row, category_id, start_index=start_index, history=history, error=True)
            return _show_quantity_prompt(session_row, nominee)

    return _show_nominee_page(session_row, category_id, start_index=start_index, history=history, error=True)


# ---------------------------------------------------------------------
# Quantity
# ---------------------------------------------------------------------

def _fit_name_to_budget(fixed_template, name):
    """fixed_template contains exactly one "{name}" placeholder. Fit
    name into whatever's left of USSD_MAX_CHARS after the rest of the
    template, shortening with "..." but never below
    MIN_FITTED_NAME_LENGTH -- the required text around it (quantity,
    code, "1. Confirm" / "2. Cancel", ...) is never the part that gets
    cut; the name is."""
    name = to_gsm7(name)
    fixed_length = len(fixed_template) - len("{name}")
    available = max(USSD_MAX_CHARS - fixed_length, MIN_FITTED_NAME_LENGTH)
    if len(name) <= available:
        return name
    keep = max(available - 3, 1)
    return name[:keep] + "..."


def _quantity_message(nominee, fee_pesewas, prefix=""):
    fixed_template = (
        f"{prefix}Votes for {{name}} ({nominee.code})?\n"
        f"{format_ghs(fee_pesewas)} per vote. Enter a number:"
    )
    name = _fit_name_to_budget(fixed_template, nominee.full_name)
    return fixed_template.format(name=name)


def _show_quantity_prompt(session_row, nominee):
    settings = get_settings()

    _set_step(session_row, STEP_AWAITING_QUANTITY, {"nominee_id": nominee.id})
    db.session.commit()

    message = _quantity_message(nominee, settings.vote_fee_pesewas)
    return _ask(session_row.session_id, message, data_type="input", field_type="number")


def _parse_quantity(raw_message):
    """A whole number of at least 1, or None for anything else (including
    "", "abc", "1.5", and negative numbers -- str.isdigit() is False for
    all of those, since it rejects a leading '-' and a '.')."""
    text = (raw_message or "").strip()
    if not text.isdigit():
        return None
    quantity = int(text)
    return quantity if quantity >= 1 else None


def _handle_quantity_entry(session_row, raw_message, now):
    data = session_row.data or {}
    nominee = Nominee.query.filter_by(id=data.get("nominee_id"), is_active=True).first()

    if nominee is None:
        return _show_main_menu_or_closed_message(session_row, now)

    settings = get_settings()

    quantity = _parse_quantity(raw_message)
    if quantity is None:
        message = _quantity_message(
            nominee, settings.vote_fee_pesewas, prefix="Please enter a whole number of at least 1.\n",
        )
        return _ask(session_row.session_id, message, data_type="input", field_type="number")

    try:
        amount_pesewas = calculate_vote_amount(quantity, settings.vote_fee_pesewas)
    except ValueError:
        return _ask(
            session_row.session_id,
            "That number is too large. Please enter a smaller quantity.",
            data_type="input", field_type="number",
        )

    _set_step(session_row, STEP_CONFIRMING, {
        "nominee_id": nominee.id,
        "quantity": quantity,
        "fee_pesewas": settings.vote_fee_pesewas,
        "amount_pesewas": amount_pesewas,
    })
    db.session.commit()

    return _ask(session_row.session_id, _confirm_message(quantity, nominee, amount_pesewas), data_type="confirm")


def _confirm_message(quantity, nominee, amount_pesewas, prefix=""):
    vote_count_text = "1 vote" if quantity == 1 else f"{quantity} votes"
    fixed_template = (
        f"{prefix}{vote_count_text} for {{name}} ({nominee.code})\n"
        f"Amount: {format_ghs(amount_pesewas)}\n"
        "Hubtel may add a small charge.\n"
        "1. Confirm\n2. Cancel"
    )
    name = _fit_name_to_budget(fixed_template, nominee.full_name)
    return fixed_template.format(name=name)


# ---------------------------------------------------------------------
# Confirm / cancel
# ---------------------------------------------------------------------

def _handle_confirm_choice(session_row, raw_message, now):
    data = session_row.data or {}
    nominee = Nominee.query.filter_by(id=data.get("nominee_id"), is_active=True).first()
    quantity = data.get("quantity")
    fee_at_confirm = data.get("fee_pesewas")
    amount_at_confirm = data.get("amount_pesewas")
    choice = raw_message.strip()

    if choice == "2":
        _delete_session(session_row.session_id)
        return _release(session_row.session_id, "Vote cancelled.")

    if nominee is None:
        _delete_session(session_row.session_id)
        return _release(session_row.session_id, "Sorry, this nominee is no longer available.")

    if choice != "1":
        message = _confirm_message(quantity, nominee, amount_at_confirm, prefix="Sorry, that's not valid.\n")
        return _ask(session_row.session_id, message, data_type="confirm")

    settings = get_settings()
    if settings.vote_fee_pesewas != fee_at_confirm:
        # The fee changed since the confirm screen was shown -- never
        # silently charge a different amount than what the voter saw.
        # Show the new total and ask again instead of continuing.
        new_amount = calculate_vote_amount(quantity, settings.vote_fee_pesewas)
        _set_step(session_row, STEP_CONFIRMING, {
            "nominee_id": nominee.id,
            "quantity": quantity,
            "fee_pesewas": settings.vote_fee_pesewas,
            "amount_pesewas": new_amount,
        })
        db.session.commit()
        message = _confirm_message(quantity, nominee, new_amount, prefix="The fee has changed.\n")
        return _ask(session_row.session_id, message, data_type="confirm")

    try:
        transaction = create_pending_transaction(
            nominee_id=nominee.id, phone=session_row.phone, quantity=quantity,
            channel="ussd", hubtel_session_id=session_row.session_id, now=now,
        )
    except ValueError:
        # Voting closed (or something else changed) between the confirm
        # screen and now -- end the session instead of crashing.
        _delete_session(session_row.session_id)
        return _release(session_row.session_id, "Sorry, voting is no longer open. Please try again later.")

    _delete_session(session_row.session_id)
    return _add_to_cart(session_row.session_id, transaction, nominee)
