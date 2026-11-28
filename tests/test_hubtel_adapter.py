"""Tests for app/providers/hubtel_adapter.py -- parsing Hubtel's
not-yet-captured fulfilment request and status-check response shapes."""

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


# ---------------------------------------------------------------------
# parse_status_response
# ---------------------------------------------------------------------

def test_parses_the_confirmed_status_fixture():
    raw_json = _load_fixture("status_check_response_CONFIRMED.json")
    status, amount_pesewas, provider_total_pesewas = parse_status_response(raw_json)
    assert status == "paid"
    # AmountAfterCharges (net, what must match the vote amount) -- never
    # Amount (gross, includes Hubtel's own fee).
    assert amount_pesewas == 500
    assert provider_total_pesewas == 510


@pytest.mark.parametrize("raw_json,expected_status", [
    ({"Status": "Paid"}, "paid"),
    ({"status": "success"}, "paid"),
    ({"Data": {"Status": "Successful"}}, "paid"),
    ({"Status": "Completed"}, "paid"),
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
    ]
    for raw_json in weird_responses:
        status, _, _ = parse_status_response(raw_json)
        assert status != "paid"


def test_amount_is_none_when_absent_or_unparseable():
    status, amount_pesewas, provider_total_pesewas = parse_status_response({"Status": "Paid"})
    assert amount_pesewas is None
    assert provider_total_pesewas is None

    status, amount_pesewas, _ = parse_status_response({"Status": "Paid", "Amount": "not-a-number"})
    assert amount_pesewas is None


def test_amount_uses_decimal_not_float_and_round_trips_exactly():
    # 0.1 + 0.2 != 0.3 in float -- this amount would expose that if the
    # parsing ever switched to float math.
    status, amount_pesewas, provider_total_pesewas = parse_status_response({
        "Status": "Paid", "AmountAfterCharges": "5.10", "Amount": "5.20",
    })
    assert amount_pesewas == 510
    assert provider_total_pesewas == 520


def test_amount_pesewas_uses_amount_after_charges_not_gross_amount():
    # The real-world bug this guards against: Hubtel's gross "Amount"
    # includes their own fee on top, so comparing it against the vote
    # amount makes a genuinely paid transaction look like a mismatch.
    status, amount_pesewas, provider_total_pesewas = parse_status_response({
        "Status": "Paid", "Amount": "1.01", "Charges": "0.01", "AmountAfterCharges": "1.00",
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
