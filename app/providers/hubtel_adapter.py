"""Parsers for the two Hubtel payloads whose exact shape we don't yet
know for certain: the Service Fulfilment request body, and the
transaction status-check response.

Isolated in this one small module on purpose: as the real shapes get
captured (see docs/HUBTEL_USSD_NOTES.md), this is the only file that
should need to change. Nothing here makes an HTTP call -- see
app/providers/hubtel.py for that.
"""

from decimal import Decimal, InvalidOperation


def parse_fulfilment_request(raw_json):
    """Return (session_id, order_id) from a fulfilment request body, or
    None if no session id can be found.

    VERIFY: the real fulfilment request body is NOT CAPTURED yet (see
    docs/HUBTEL_USSD_NOTES.md). This is deliberately conservative: it
    accepts only the exact field names "SessionId" and "OrderId"
    (case-sensitive), and looks nowhere else. Once the real body has been
    captured (check the HubtelLog table/the admin log endpoint), update
    this function to match it rather than guessing further than this.

    This is only ever used to find WHICH transaction to look at -- never
    to decide whether it was paid. That's check_transaction_status's job.
    """
    if not isinstance(raw_json, dict):
        return None

    session_id = raw_json.get("SessionId")
    if not isinstance(session_id, str) or not session_id:
        return None

    order_id = raw_json.get("OrderId")
    order_id = order_id if isinstance(order_id, str) and order_id else None

    return session_id, order_id


def _decimal_cedis_to_pesewas(value):
    """Parse a cedis amount (a string or number) into whole pesewas using
    Decimal arithmetic, or None if it isn't a clean number, or has more
    than 2 decimal places. Never float math."""
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None

    pesewas = decimal_value * 100
    if pesewas != pesewas.to_integral_value():
        return None

    return int(pesewas)


def _find_amount_pesewas(data, *field_names):
    """Try each field name in order; return the first one that parses
    cleanly as a cedis amount. None if none of them do."""
    for field_name in field_names:
        if field_name not in data:
            continue
        amount = _decimal_cedis_to_pesewas(data[field_name])
        if amount is not None:
            return amount
    return None


def parse_status_response(raw_json):
    """Best-effort read of Hubtel's status-check response.

    Returns (status, amount_pesewas, provider_total_pesewas):
    - status is one of "paid", "failed", "pending", "unknown".
    - amount_pesewas is the vote amount Hubtel reports being paid, in
      pesewas -- None unless confidently found.
    - provider_total_pesewas is Hubtel's full charged total (including
      their own fee), in pesewas -- None unless confidently found.

    VERIFY: the real response format is NOT CAPTURED yet (see
    docs/HUBTEL_USSD_NOTES.md). This guesses at commonly-used field names
    ("Status"/"status"/"TransactionStatus" for the status, "Amount" for
    the vote amount, "Total"/"AmountCharged" for Hubtel's total --
    possibly nested under "Data", the way several of Hubtel's other APIs
    shape their responses) and falls back to "unknown"/None for anything
    it doesn't confidently recognise.

    "unknown" must NEVER be treated as "paid". If this function can't
    positively confirm a payment, the only safe assumption is that it
    hasn't happened -- treating an unrecognised response as "paid" would
    be the kind of bug that gives away free votes.
    """
    if not isinstance(raw_json, dict):
        return "unknown", None, None

    data = raw_json.get("Data") if isinstance(raw_json.get("Data"), dict) else raw_json

    status_text = str(
        data.get("Status") or data.get("status") or data.get("TransactionStatus") or ""
    ).strip().lower()

    if status_text in ("paid", "success", "successful", "completed"):
        status = "paid"
    elif status_text in ("failed", "failure", "declined", "cancelled", "canceled"):
        status = "failed"
    elif status_text in ("pending", "processing", "initiated"):
        status = "pending"
    else:
        status = "unknown"

    amount_pesewas = _find_amount_pesewas(data, "Amount", "amount")
    provider_total_pesewas = _find_amount_pesewas(data, "Total", "AmountCharged", "total")

    return status, amount_pesewas, provider_total_pesewas
