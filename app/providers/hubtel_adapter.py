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


def _status_data(raw_json):
    """The dict to read status/amount/order-id fields from -- Hubtel
    nests some of its other APIs' responses under "Data", so we check
    there first if present."""
    if not isinstance(raw_json, dict):
        return {}
    return raw_json.get("Data") if isinstance(raw_json.get("Data"), dict) else raw_json


def raw_status_text(raw_json):
    """The raw status word from a status-check response, exactly as
    Hubtel sent it (not lower-cased), or "" if there isn't one. Used for
    building a readable last_status_note when the word isn't one we
    recognise -- shared by parse_status_response and
    scripts/explain_transaction.py so the two never disagree."""
    data = _status_data(raw_json)
    return str(data.get("Status") or data.get("status") or data.get("TransactionStatus") or "").strip()


def find_order_id_in_status_response(raw_json):
    """Hubtel's own order id as reported by the status-check response,
    or None if it isn't present. Compared against
    Transaction.hubtel_order_id (learned from the fulfilment request) as
    an extra safety check before a "Paid" status is trusted -- see
    process_hubtel_payment."""
    data = _status_data(raw_json)
    order_id = data.get("OrderId")
    if not isinstance(order_id, str) or not order_id:
        order_id = data.get("orderId")
    return order_id if isinstance(order_id, str) and order_id else None


def parse_status_response(raw_json):
    """Best-effort read of Hubtel's status-check response.

    Returns (status, amount_pesewas, provider_total_pesewas):
    - status is one of "paid", "unpaid", "refunded", "failed", "pending",
      "unknown". Confirmed from Hubtel's docs (26 Nov 2026): the status
      word is one of "Paid", "Unpaid" or "Refunded" -- "failed"/"pending"
      are kept as a defensive fallback for older/other wording we'd
      already seen, not something Hubtel's current docs promise.
    - amount_pesewas is the vote amount Hubtel reports being paid, in
      pesewas -- None unless confidently found.
    - provider_total_pesewas is Hubtel's full charged total (including
      their own fee), in pesewas -- None unless confidently found.

    CONFIRMED (28 Nov 2026, via scripts/check_hubtel_status.py against a
    real paid transaction): Hubtel's response carries "Amount" (the gross
    amount actually charged to the payer, INCLUDING Hubtel's own
    "Charges" fee on top) and "AmountAfterCharges" (the net amount left
    after Hubtel's fee is deducted). The vote amount we must compare
    against Transaction.amount_pesewas is the NET figure --
    "AmountAfterCharges" -- never the gross "Amount". Using "Amount" here
    was the bug that made a genuinely paid transaction look like an
    amount mismatch and get stuck needing review: a GH₵1.00 vote fee
    comes back as Amount=1.01/Charges=0.01/AmountAfterCharges=1.00, and
    only the last of those equals what we expect. "Amount" is kept as
    provider_total_pesewas (for reporting only, never compared against
    the expected amount).

    "unknown" must NEVER be treated as "paid". If this function can't
    positively confirm a payment, the only safe assumption is that it
    hasn't happened -- treating an unrecognised response as "paid" would
    be the kind of bug that gives away free votes. Likewise "unpaid" is
    never "failed": Hubtel's "Unpaid" means "not paid yet", not "this
    attempt failed" -- it's meant to be treated like "pending".
    """
    if not isinstance(raw_json, dict):
        return "unknown", None, None

    data = _status_data(raw_json)
    status_text = raw_status_text(raw_json).lower()

    if status_text in ("paid", "success", "successful", "completed"):
        status = "paid"
    elif status_text == "unpaid":
        status = "unpaid"
    elif status_text == "refunded":
        status = "refunded"
    elif status_text in ("failed", "failure", "declined", "cancelled", "canceled"):
        status = "failed"
    elif status_text in ("pending", "processing", "initiated"):
        status = "pending"
    else:
        status = "unknown"

    amount_pesewas = _find_amount_pesewas(data, "AmountAfterCharges", "amountAfterCharges")
    provider_total_pesewas = _find_amount_pesewas(data, "Amount", "amount")

    return status, amount_pesewas, provider_total_pesewas
