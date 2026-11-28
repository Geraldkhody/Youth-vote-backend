"""Parsers for the two Hubtel payloads whose exact shape we don't yet
know for certain: the Service Fulfilment request body, and the
transaction status-check response.

Isolated in this one small module on purpose: as the real shapes get
captured (see docs/HUBTEL_USSD_NOTES.md), this is the only file that
should need to change. Nothing here makes an HTTP call -- see
app/providers/hubtel.py for that.
"""

import json
from decimal import Decimal, InvalidOperation


def _ci_lookup(d, *names):
    """Case-insensitive dict key lookup: tries each name's exact spelling
    first, then falls back to a case-insensitive scan. None if nothing
    matches, or d isn't a dict.

    This is the "case-insensitively, as a safety net" layer -- the real,
    confirmed field names (see parse_status_response's docstring) are
    tried first via exact match; this only matters if Hubtel ever
    changes the casing on us."""
    if not isinstance(d, dict):
        return None
    for name in names:
        if name in d:
            return d[name]
    lowered = {key.lower(): value for key, value in d.items() if isinstance(key, str)}
    for name in names:
        match = lowered.get(name.lower())
        if match is not None:
            return match
    return None


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


def _find_amount_pesewas(data, field_name):
    """Read field_name (case-insensitively) from data and parse it
    cleanly as a cedis amount, or None if it's missing or unparseable."""
    value = _ci_lookup(data, field_name)
    if value is None:
        return None
    return _decimal_cedis_to_pesewas(value)


def _status_data(raw_json):
    """The dict to read status/amount/order-id fields from.

    CONFIRMED (28 Nov 2026, real capture): Hubtel's status-check response
    nests all of this under a top-level "data" key (lowercase), alongside
    "message" and "responseCode" -- e.g. {"message": "Successful",
    "responseCode": "0000", "data": {"status": "Paid", ...}}. Looked up
    case-insensitively ("data" vs "Data") as a safety net, in case Hubtel
    ever changes the casing. Falls back to the top-level dict itself if
    there's no such nested dict, so a flatter/simulated body (no
    envelope at all) still works."""
    if not isinstance(raw_json, dict):
        return {}
    nested = _ci_lookup(raw_json, "data")
    return nested if isinstance(nested, dict) else raw_json


def raw_status_text(raw_json):
    """The raw status word from a status-check response, exactly as
    Hubtel sent it (not lower-cased), or "" if there isn't one. Used for
    building a readable last_status_note when the word isn't one we
    recognise -- shared by parse_status_response and
    scripts/explain_transaction.py so the two never disagree."""
    data = _status_data(raw_json)
    value = _ci_lookup(data, "status", "TransactionStatus")
    return str(value).strip() if value is not None else ""


def find_order_id_in_status_response(raw_json):
    """Hubtel's own id for this payment, as reported by the status-check
    response, or None if it isn't present. Compared against
    Transaction.hubtel_order_id (learned from the fulfilment request) as
    an extra safety check before a "Paid" status is trusted -- see
    process_hubtel_payment.

    CONFIRMED (28 Nov 2026, real capture): the real response carries this
    as data.transactionId, not "OrderId" -- "OrderId" is tried first
    anyway, in case a different endpoint or a future version uses it,
    but transactionId is what we've actually seen."""
    data = _status_data(raw_json)
    order_id = _ci_lookup(data, "OrderId")
    if order_id is None:
        order_id = _ci_lookup(data, "transactionId")
    return order_id if isinstance(order_id, str) and order_id else None


def parse_status_response(raw_json):
    """Best-effort read of Hubtel's status-check response.

    Accepts either an already-parsed dict (what check_transaction_status
    returns -- response.json() has already run) or a raw JSON string/
    bytes, so callers that haven't parsed it yet don't have to.

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

    CONFIRMED (28 Nov 2026, real capture): Hubtel's response carries
    "amount" (the gross amount actually charged to the payer, INCLUDING
    Hubtel's own "charges" fee on top) and "amountAfterCharges" (the net
    amount left after Hubtel's fee is deducted). The vote amount we must
    compare against Transaction.amount_pesewas is the NET figure --
    "amountAfterCharges" -- never the gross "amount". Using "amount" here
    was the bug that made a genuinely paid transaction look like an
    amount mismatch and get stuck needing review: a GH₵1.00 vote fee
    comes back as amount=1.01/charges=0.01/amountAfterCharges=1.00, and
    only the last of those equals what we expect. "amount" is kept as
    provider_total_pesewas (for reporting only, never compared against
    the expected amount). Field names are matched case-insensitively
    (see _ci_lookup) as a safety net against Hubtel changing casing --
    "amount"/"Amount", "data"/"Data" etc. are treated the same.

    A "Paid" status word is trusted only when ALL of these hold --
    anything else and the safe assumption is that the payment hasn't
    been confirmed, exactly like an unrecognised response:
    - responseCode is exactly "0000" (CONFIRMED 28 Nov 2026) -- this is
      Hubtel's own signal that the status-check call itself succeeded
      and the data payload means what it says. A "Paid" status word
      inside a response that doesn't even claim success is not trusted.
    - amount - charges == amountAfterCharges, exactly (in whole pesewas)
      -- if Hubtel's own three money fields disagree with each other,
      the response is internally inconsistent and amount_pesewas is
      reported as None (so evaluate_payment_check treats it as
      unreadable, never as a confirmed amount).
    - the resulting pesewas figure is a whole, positive number (the
      existing whole-pesewas check, plus a new positive check -- a
      zero/negative "paid" amount is nonsensical and never trusted).

    "unknown" must NEVER be treated as "paid". If this function can't
    positively confirm a payment, the only safe assumption is that it
    hasn't happened -- treating an unrecognised response as "paid" would
    be the kind of bug that gives away free votes. Likewise "unpaid" is
    never "failed": Hubtel's "Unpaid" means "not paid yet", not "this
    attempt failed" -- it's meant to be treated like "pending".
    """
    if isinstance(raw_json, (str, bytes)):
        try:
            raw_json = json.loads(raw_json)
        except (TypeError, ValueError):
            return "unknown", None, None

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

    amount_pesewas = _find_amount_pesewas(data, "AmountAfterCharges")
    provider_total_pesewas = _find_amount_pesewas(data, "Amount")
    charges_pesewas = _find_amount_pesewas(data, "Charges")

    if status == "paid":
        response_code = _ci_lookup(raw_json, "responseCode")
        if response_code != "0000":
            # The envelope itself isn't reporting success -- a "Paid"
            # status word inside it can't be trusted either.
            status = "unknown"
        elif (
            provider_total_pesewas is not None
            and charges_pesewas is not None
            and amount_pesewas is not None
            and provider_total_pesewas - charges_pesewas != amount_pesewas
        ):
            # Hubtel's own money fields disagree with each other --
            # never trust an internally inconsistent response enough to
            # create a vote.
            amount_pesewas = None
        elif amount_pesewas is not None and amount_pesewas <= 0:
            amount_pesewas = None

    return status, amount_pesewas, provider_total_pesewas
