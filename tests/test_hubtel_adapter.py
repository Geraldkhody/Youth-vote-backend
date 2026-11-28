"""Tests for app/providers/hubtel_adapter.py -- parsing Hubtel's
fulfilment request and status-check response shapes.

Fixtures under tests/fixtures named *_REAL* are byte-for-byte (or, where
noted in their own "_note" field, partially) real captured Hubtel
bodies -- never invented. Fixtures named *_ASSUMED* or *_DOCUMENTED* are
explicitly NOT real captures; see each file's own "_note" for what it's
based on. See docs/HUBTEL_USSD_NOTES.md and test_fixtures_are_honest
below.
"""

import json
from pathlib import Path

import pytest

from app.providers.hubtel_adapter import (
    find_order_id_in_status_response,
    parse_fulfilment_request,
    parse_status_response,
    raw_status_text,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


# ---------------------------------------------------------------------
# parse_fulfilment_request
# ---------------------------------------------------------------------

def test_parses_the_assumed_fixture():
    raw_json = _load_fixture("fulfilment_request_ASSUMED.json")
    session_id, order_id = parse_fulfilment_request(raw_json)
    assert session_id == "sim-session-abc123"
    assert order_id == "ORDER-0001"


def test_returns_none_without_a_session_id():
    assert parse_fulfilment_request({"OrderId": "ORDER-1"}) is None
    assert parse_fulfilment_request({}) is None
    assert parse_fulfilment_request(None) is None
    assert parse_fulfilment_request([]) is None
    assert parse_fulfilment_request({"SessionId": ""}) is None
    assert parse_fulfilment_request({"SessionId": 123}) is None


def test_order_id_is_none_when_missing_or_wrong_type():
    session_id, order_id = parse_fulfilment_request({"SessionId": "s1"})
    assert session_id == "s1"
    assert order_id is None

    session_id, order_id = parse_fulfilment_request({"SessionId": "s1", "OrderId": 123})
    assert order_id is None


def test_does_not_look_at_other_field_names():
    # Deliberately conservative: only the exact "SessionId" field counts.
    assert parse_fulfilment_request({"sessionId": "s1", "session_id": "s1"}) is None


def test_still_finds_session_id_when_a_real_shaped_order_info_block_is_present():
    """Documented real fulfilment shape (not a full captured body --
    see docs/HUBTEL_USSD_NOTES.md): SessionId/OrderId stay top-level,
    with an OrderInfo.Status / OrderInfo.Payment.AmountAfterCharges
    block alongside. parse_fulfilment_request must keep ignoring
    OrderInfo entirely -- it only ever decides WHICH transaction to
    look at, never whether it was paid."""
    raw_json = {
        "SessionId": "e38835ef7748448fafe89f2e22da5cf7",
        "OrderId": "1cde0454d1bf408cbce2005bc2228111",
        "OrderInfo": {"Status": "Paid", "Payment": {"AmountAfterCharges": 1.0}},
    }
    session_id, order_id = parse_fulfilment_request(raw_json)
    assert session_id == "e38835ef7748448fafe89f2e22da5cf7"
    assert order_id == "1cde0454d1bf408cbce2005bc2228111"


# ---------------------------------------------------------------------
# parse_status_response -- contract tests against the REAL fixtures
# ---------------------------------------------------------------------

def test_parses_the_real_paid_fixture():
    """tests/fixtures/hubtel_status_paid_REAL.json is the exact body
    Hubtel returned for a real GH₵1.00 (100 pesewas) vote payment --
    pasted verbatim, never invented. This is the regression test for
    the bug where this body parsed as outcome "unknown" because the
    response nests everything under lowercase "data" (plus a
    "responseCode"/"message" envelope), not the "Data" shape the parser
    used to assume."""
    raw_json = _load_fixture("hubtel_status_paid_REAL.json")

    status, amount_pesewas, provider_total_pesewas = parse_status_response(raw_json)
    assert status == "paid"
    assert amount_pesewas == 100
    assert provider_total_pesewas == 101
    assert provider_total_pesewas - amount_pesewas == 1  # charges, 1 pesewa

    order_id = find_order_id_in_status_response(raw_json)
    assert order_id == "1cde0454d1bf408cbce2005bc2228111"


def test_parses_the_real_quantity_2_paid_fixture():
    """tests/fixtures/hubtel_status_paid_REAL_quantity2.json: a second
    real payment's money fields (GH₵2.10 gross / GH₵0.10 charges /
    GH₵2.00 net, a 2-vote purchase)."""
    raw_json = _load_fixture("hubtel_status_paid_REAL_quantity2.json")

    status, amount_pesewas, provider_total_pesewas = parse_status_response(raw_json)
    assert status == "paid"
    assert amount_pesewas == 200
    assert provider_total_pesewas == 210
    assert provider_total_pesewas - amount_pesewas == 10  # charges, 10 pesewas


def test_parses_the_documented_unpaid_and_refunded_fixtures():
    """These two are explicitly DOCUMENTED SAMPLES, not real captures --
    see each file's own "_note". Still built in the confirmed real
    envelope shape, so they exercise the same code path."""
    unpaid = _load_fixture("hubtel_status_unpaid_DOCUMENTED.json")
    status, amount_pesewas, provider_total_pesewas = parse_status_response(unpaid)
    assert status == "unpaid"
    assert amount_pesewas is None
    assert provider_total_pesewas is None

    refunded = _load_fixture("hubtel_status_refunded_DOCUMENTED.json")
    status, amount_pesewas, provider_total_pesewas = parse_status_response(refunded)
    assert status == "refunded"


# ---------------------------------------------------------------------
# parse_status_response -- status word / responseCode gate
# ---------------------------------------------------------------------

@pytest.mark.parametrize("raw_json,expected_status", [
    # Full confirmed-real envelope (responseCode "0000" + nested data) --
    # a "Paid"-equivalent word is trusted.
    ({"responseCode": "0000", "data": {"status": "Paid"}}, "paid"),
    ({"responseCode": "0000", "data": {"status": "success"}}, "paid"),
    ({"responseCode": "0000", "Data": {"Status": "Successful"}}, "paid"),
    ({"responseCode": "0000", "data": {"status": "Completed"}}, "paid"),
    # The same status word OUTSIDE that envelope -- correctly refused.
    # This is the exact shape every mock in this suite used to use, and
    # the exact shape that must never again be trusted as "paid".
    ({"Status": "Paid"}, "unknown"),
    ({"responseCode": "0001", "data": {"status": "Paid"}}, "unknown"),
    # Unpaid/Refunded/Failed/Pending are never gated by responseCode --
    # only a "Paid" word needs the envelope to be trusted.
    ({"Status": "Unpaid"}, "unpaid"),
    ({"Status": "unpaid"}, "unpaid"),
    ({"Status": "Refunded"}, "refunded"),
    ({"Status": "refunded"}, "refunded"),
    ({"Status": "Failed"}, "failed"),
    ({"Status": "Declined"}, "failed"),
    ({"Status": "Pending"}, "pending"),
    ({"Status": "Processing"}, "pending"),
    ({"Status": "SomethingWeird"}, "unknown"),
    ({}, "unknown"),
    ([], "unknown"),
    (None, "unknown"),
])
def test_parse_status_response_status_word(raw_json, expected_status):
    status, _, _ = parse_status_response(raw_json)
    assert status == expected_status


def test_unknown_is_never_treated_as_paid():
    weird_responses = [
        {"Status": "???"}, {"foo": "bar"}, {"Status": None}, {"Status": 123},
        {"responseCode": "0000", "data": {"status": "Paid", "amountAfterCharges": "-1.00"}},
    ]
    for raw_json in weird_responses:
        status, amount_pesewas, _ = parse_status_response(raw_json)
        if status == "paid":
            # Allowed to still say "paid" (that's the literal status
            # word), but never with a usable amount -- see
            # evaluate_payment_check, which refuses to act without one.
            assert amount_pesewas is None
        else:
            assert status != "paid"


def test_amount_is_none_when_absent_or_unparseable():
    status, amount_pesewas, provider_total_pesewas = parse_status_response({"Status": "Paid"})
    assert amount_pesewas is None
    assert provider_total_pesewas is None

    status, amount_pesewas, _ = parse_status_response(
        {"responseCode": "0000", "data": {"status": "Paid", "amountAfterCharges": "not-a-number"}}
    )
    assert amount_pesewas is None


def test_amount_uses_decimal_not_float_and_round_trips_exactly():
    # 0.1 + 0.2 != 0.3 in float -- this amount would expose that if the
    # parsing ever switched to float math.
    status, amount_pesewas, provider_total_pesewas = parse_status_response({
        "responseCode": "0000",
        "data": {"status": "Paid", "amountAfterCharges": "5.10", "amount": "5.20", "charges": "0.10"},
    })
    assert status == "paid"
    assert amount_pesewas == 510
    assert provider_total_pesewas == 520


def test_amount_pesewas_uses_amount_after_charges_not_gross_amount():
    # The real-world bug this guards against: Hubtel's gross "amount"
    # includes their own fee on top, so comparing it against the vote
    # amount makes a genuinely paid transaction look like a mismatch.
    status, amount_pesewas, provider_total_pesewas = parse_status_response({
        "responseCode": "0000",
        "data": {"status": "Paid", "amount": "1.01", "charges": "0.01", "amountAfterCharges": "1.00"},
    })
    assert status == "paid"
    assert amount_pesewas == 100
    assert provider_total_pesewas == 101


def test_inconsistent_money_fields_are_never_trusted_even_with_paid_status_and_good_response_code():
    """Hubtel's own amount/charges/amountAfterCharges disagreeing with
    each other is treated exactly like an unreadable amount -- the
    status word and responseCode alone are not enough to create a
    vote."""
    status, amount_pesewas, provider_total_pesewas = parse_status_response({
        "responseCode": "0000",
        "data": {"status": "Paid", "amount": "1.01", "charges": "0.01", "amountAfterCharges": "1.50"},
    })
    assert status == "paid"
    assert amount_pesewas is None
    assert provider_total_pesewas == 101


def test_zero_or_negative_amount_after_charges_is_never_trusted():
    status, amount_pesewas, _ = parse_status_response({
        "responseCode": "0000",
        "data": {"status": "Paid", "amount": "0.00", "charges": "0.00", "amountAfterCharges": "0.00"},
    })
    assert status == "paid"
    assert amount_pesewas is None


def test_parse_status_response_accepts_a_json_string():
    body = json.dumps({
        "responseCode": "0000",
        "data": {"status": "Paid", "amountAfterCharges": "1.00", "amount": "1.00", "charges": "0.00"},
    })
    status, amount_pesewas, _ = parse_status_response(body)
    assert status == "paid"
    assert amount_pesewas == 100


def test_parse_status_response_rejects_unparseable_string():
    status, amount_pesewas, provider_total_pesewas = parse_status_response("not json at all")
    assert status == "unknown"
    assert amount_pesewas is None
    assert provider_total_pesewas is None


def test_field_names_are_matched_case_insensitively_as_a_safety_net():
    # The primary/confirmed spelling is lowercase; this proves a
    # differently-cased response still parses the same way.
    status, amount_pesewas, provider_total_pesewas = parse_status_response({
        "ResponseCode": "0000",
        "DATA": {"STATUS": "PAID", "AMOUNTAFTERCHARGES": "1.00", "AMOUNT": "1.01", "CHARGES": "0.01"},
    })
    assert status == "paid"
    assert amount_pesewas == 100
    assert provider_total_pesewas == 101


# ---------------------------------------------------------------------
# raw_status_text / find_order_id_in_status_response
# ---------------------------------------------------------------------

def test_raw_status_text_returns_original_casing():
    assert raw_status_text({"Status": "Paid"}) == "Paid"
    assert raw_status_text({"Status": "SomeBrandNewWord"}) == "SomeBrandNewWord"
    assert raw_status_text({}) == ""
    assert raw_status_text(None) == ""


def test_find_order_id_in_status_response():
    assert find_order_id_in_status_response({"OrderId": "ORDER-1"}) == "ORDER-1"
    assert find_order_id_in_status_response({"Data": {"OrderId": "ORDER-2"}}) == "ORDER-2"
    assert find_order_id_in_status_response({}) is None
    assert find_order_id_in_status_response({"OrderId": 123}) is None
    assert find_order_id_in_status_response(None) is None


def test_find_order_id_falls_back_to_transaction_id():
    # CONFIRMED (28 Nov 2026, real capture): the real response reports
    # this as data.transactionId, not "OrderId".
    assert find_order_id_in_status_response(
        {"data": {"transactionId": "1cde0454d1bf408cbce2005bc2228111"}}
    ) == "1cde0454d1bf408cbce2005bc2228111"
    # "OrderId" still wins if both are somehow present.
    assert find_order_id_in_status_response(
        {"data": {"OrderId": "ORDER-1", "transactionId": "TXN-1"}}
    ) == "ORDER-1"


# ---------------------------------------------------------------------
# Fixture hygiene -- tests must use real captured bodies, never
# invented ones (see docs/HUBTEL_USSD_NOTES.md).
# ---------------------------------------------------------------------

# Substrings that only ever show up in made-up test data, never in
# anything Hubtel actually sent us.
_FAKE_LOOKING_MARKERS = ("sess-", "sim-session", "ORDER-0001")


def test_fixtures_are_honest():
    """Every fixture file must be valid JSON. Any file named *_REAL*
    must not contain fake-looking placeholder values -- if part of a
    real capture is genuinely unavailable, the honest thing to do is
    leave that field out (see hubtel_status_paid_REAL_quantity2.json's
    own "_note"), never invent a plausible-looking stand-in."""
    fixture_paths = sorted(FIXTURES_DIR.glob("*.json"))
    assert fixture_paths, "expected at least one fixture file"

    for path in fixture_paths:
        with open(path) as f:
            text = f.read()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as error:
            pytest.fail(f"{path.name} is not valid JSON: {error}")

        if "_REAL" in path.name.upper():
            lowered = text.lower()
            for marker in _FAKE_LOOKING_MARKERS:
                assert marker.lower() not in lowered, (
                    f"{path.name} is named as a REAL fixture but contains "
                    f"the fake-looking marker {marker!r}"
                )

        del parsed  # only the "is it valid JSON" check matters for non-REAL files
