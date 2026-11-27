"""Handles Hubtel's Service Fulfilment request: verifies the payment via
the status-check API, records the vote, and sends the final callback.

Design rules (do not weaken these):
- The fulfilment request body is NOT trusted for anything except which
  transaction to look at (its SessionId). The payment itself is only
  ever confirmed by calling Hubtel's status-check API, and the amount we
  compare is the vote amount only -- never Hubtel's own charge on top.
- Anything we can't confidently read counts as "unknown", and "unknown"
  never creates a vote.
- record_successful_payment (app/services/transactions.py) is the ONLY
  place a Vote is ever created. Nothing in this file creates one
  directly.
- We never hold a database row lock while making an HTTP call to Hubtel.
  The status check and the final callback both run with no lock held;
  record_successful_payment / mark_payment_failed take their own row
  lock only afterwards, briefly, to apply the result we already have.
"""

import logging
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app

from app.extensions import db
from app.models.transaction import Transaction
from app.providers.hubtel import HubtelError, check_transaction_status
from app.providers.hubtel_adapter import parse_fulfilment_request, parse_status_response
from app.services.transactions import mark_payment_failed, record_successful_payment

logger = logging.getLogger(__name__)

# Hubtel requires the final callback within one hour of receiving the
# fulfilment request (fulfilment_received_at) -- named so the sweep's
# retry schedule (app/cli.py) and the admin "callback_overdue" filter
# (app/routes/transactions_admin.py) can't drift out of sync with it.
HUBTEL_CALLBACK_DEADLINE_MINUTES = 60

# Safety margin before the one-hour deadline: once we're this far past
# fulfilment with no callback sent, stop retrying and flag it for a
# human instead of risking a retry landing after Hubtel's cutoff.
CALLBACK_GIVE_UP_MINUTES = 55

# Retry cadence once we know when fulfilment happened: no cooldown for
# the first CALLBACK_FAST_RETRY_MINUTES (so a once-a-minute sweep run can
# retry every time), then CALLBACK_SLOW_RETRY_COOLDOWN_SECONDS (5
# minutes) between attempts. A transaction with no recorded fulfilment
# time at all (shouldn't normally happen for a 'success' one) falls back
# to the older, simpler CALLBACK_RETRY_COOLDOWN_SECONDS.
CALLBACK_FAST_RETRY_MINUTES = 10
CALLBACK_SLOW_RETRY_COOLDOWN_SECONDS = 300

MAX_CALLBACK_ATTEMPTS = 10
CALLBACK_RETRY_COOLDOWN_SECONDS = 120
CALLBACK_TIMEOUT_SECONDS = 10


def _naive_utc_now():
    """Matches how the rest of this codebase stores "now" (see
    app/services/voting_settings.py for why)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def handle_fulfilment_request(raw_json):
    """Entry point for the fulfilment route. Returns one of "unparsed",
    "unknown_session", or "processed" -- for logging only, not a
    contract Hubtel sees (the route always replies the same way; see
    docs/HUBTEL_USSD_NOTES.md for why the reply shape is still an open
    question).

    The body only tells us WHICH transaction to look at, by its
    hubtel_session_id -- see the module docstring for why nothing else
    in it is trusted.
    """
    parsed = parse_fulfilment_request(raw_json)
    if parsed is None:
        return "unparsed"

    session_id, order_id = parsed

    transaction = Transaction.query.filter_by(hubtel_session_id=session_id).first()
    if transaction is None:
        return "unknown_session"

    if order_id is not None:
        transaction.hubtel_order_id = order_id
    transaction.fulfilment_received_at = _naive_utc_now()
    db.session.commit()

    process_hubtel_payment(transaction.id)
    return "processed"


def process_hubtel_payment(transaction_id, now=None):
    """Check Hubtel's status-check API for one transaction and act on
    the result. Safe to call repeatedly -- by the fulfilment endpoint, or
    later by the sweep -- since it never creates more than one vote (that
    guarantee lives in record_successful_payment, not here).

    The HTTP call to Hubtel happens with NO database row lock held.

    now lets tests exercise the callback/retry schedule with a
    controllable clock instead of real sleeping -- defaults to the real
    current time.
    """
    now = now if now is not None else _naive_utc_now()
    transaction = Transaction.query.filter_by(id=transaction_id).first()
    if transaction is None:
        return

    # Normally only a 'pending' transaction has anything left to decide.
    # A 'success' one is also let through here -- not to re-decide
    # paid/failed (record_successful_payment/mark_payment_failed are both
    # no-ops on an already-'success' row anyway), but so that if Hubtel
    # pings us again after we've already recorded the vote, we still
    # notice a "Refunded" status and can flag it (see the "refunded"
    # branch below). Anything else ('failed'/'cancelled') is truly done.
    if transaction.status not in ("pending", "success"):
        return

    reference_for_hubtel = transaction.hubtel_session_id or transaction.reference

    try:
        if current_app.config.get("HUBTEL_MODE") == "fake":
            # Dev/local only (create_app() refuses this combined with
            # APP_ENV=production) -- always reports exactly the expected
            # amount as paid, so the whole flow can be exercised without
            # a real Hubtel account.
            status = "paid"
            amount_pesewas = transaction.amount_pesewas
            provider_total_pesewas = transaction.amount_pesewas
        else:
            _, raw_json = check_transaction_status(reference_for_hubtel)
            status, amount_pesewas, provider_total_pesewas = parse_status_response(raw_json)
    except HubtelError as error:
        logger.warning("Hubtel status check failed for transaction %s: %s", transaction_id, error)
        status, amount_pesewas, provider_total_pesewas = "unknown", None, None

    transaction.last_status_check_at = now
    db.session.commit()

    if status == "refunded":
        # No vote existed yet ('pending'): flag it, create nothing.
        # A vote already existed ('success'): the vote is NOT touched or
        # removed -- reversing it is an organisers' decision, not ours --
        # just flagged for review, and no final callback is sent (see
        # send_final_callback's needs_review check).
        reason = (
            "refunded after vote was recorded" if transaction.status == "success"
            else "refunded by Hubtel"
        )
        transaction.needs_review = True
        transaction.review_reason = reason
        db.session.commit()
        return

    if transaction.status == "success":
        # Already decided (and not refunded) -- nothing else to do.
        return

    if status == "paid" and amount_pesewas is not None:
        record_successful_payment(
            transaction_id, paid_amount_pesewas=amount_pesewas,
            provider_total_pesewas=provider_total_pesewas, now=now,
        )
        send_final_callback(transaction_id, now=now)
        return

    if status == "failed":
        mark_payment_failed(transaction_id, reason="Hubtel's status-check API reported this payment failed")
        return

    # "pending", "unpaid" (not paid yet -- treated the same as "pending",
    # never as a failure), "unknown", a timeout/non-200 (surfaced above as
    # "unknown"), or "paid" without a confidently-read amount: change
    # nothing. The sweep (`flask hubtel-sweep`) will try again later.


def send_final_callback(transaction_id, now=None):
    """Send Hubtel's final callback for one 'success' transaction, at
    most once.

    now lets tests exercise the one-hour deadline with a controllable
    clock instead of real sleeping -- defaults to the real current time.

    "At most once" is enforced with an atomic claim rather than a lock
    held across the HTTP call: one UPDATE sets callback_last_attempt_at
    to now, but ONLY on a row that is still 'success', has no
    callback_sent_at yet, has a hubtel_order_id, has fewer than
    MAX_CALLBACK_ATTEMPTS attempts already, and whose last attempt (if
    any) was more than CALLBACK_RETRY_COOLDOWN_SECONDS ago. The database
    tells us how many rows that UPDATE actually changed. If two
    processes -- an HTTP request and the sweep, or two overlapping
    sweeps -- both reach this at nearly the same instant, only one of
    them can "win" that UPDATE; the other sees 0 rows changed and gives
    up immediately, without ever making a second real call to Hubtel.
    This is the same idea as the SELECT ... FOR UPDATE row lock in
    record_successful_payment, but needs no lock held across the HTTP
    call itself -- the UPDATE's WHERE clause IS the claim, and it's a
    single, instant database statement.

    If this transaction ended in needs_review (e.g. a wrong amount)
    instead of 'success', it is never eligible here (status != 'success'
    always fails the claim) -- what Hubtel should be told in that case,
    if anything, is still an open question (see docs/HUBTEL_USSD_NOTES.md).

    Never raises -- any error sending the callback is recorded on the
    transaction (callback_attempts, callback_last_error) instead.
    """
    now = now if now is not None else _naive_utc_now()

    # Hubtel's one-hour callback deadline, measured from
    # fulfilment_received_at: once we're CALLBACK_GIVE_UP_MINUTES in with
    # no callback sent, stop retrying and flag it instead of risking a
    # retry landing after the real cutoff. Transactions with no recorded
    # fulfilment time (shouldn't normally happen for a 'success' one, but
    # defensively handled) skip this check -- there's no clock to measure
    # against, so retries fall back to the attempt-count cap below.
    pre_check = Transaction.query.filter_by(id=transaction_id).first()
    if (
        pre_check is not None
        and pre_check.status == "success"
        and pre_check.callback_sent_at is None
        and pre_check.fulfilment_received_at is not None
        and now - pre_check.fulfilment_received_at >= timedelta(minutes=CALLBACK_GIVE_UP_MINUTES)
    ):
        (
            Transaction.query
            .filter(Transaction.id == transaction_id)
            .filter(Transaction.status == "success")
            .filter(Transaction.callback_sent_at.is_(None))
            .update({
                "needs_review": True,
                "review_reason": "final callback not sent within one hour",
            }, synchronize_session=False)
        )
        db.session.commit()
        return

    if pre_check is not None and pre_check.fulfilment_received_at is not None:
        minutes_since_fulfilment = (now - pre_check.fulfilment_received_at).total_seconds() / 60
        cooldown_seconds = (
            0 if minutes_since_fulfilment < CALLBACK_FAST_RETRY_MINUTES
            else CALLBACK_SLOW_RETRY_COOLDOWN_SECONDS
        )
    else:
        cooldown_seconds = CALLBACK_RETRY_COOLDOWN_SECONDS

    cooldown_cutoff = now - timedelta(seconds=cooldown_seconds)

    claimed_rows = (
        Transaction.query
        .filter(Transaction.id == transaction_id)
        .filter(Transaction.status == "success")
        .filter(Transaction.callback_sent_at.is_(None))
        .filter(Transaction.needs_review.is_(False))
        .filter(Transaction.hubtel_order_id.isnot(None))
        .filter(Transaction.callback_attempts < MAX_CALLBACK_ATTEMPTS)
        .filter(db.or_(
            Transaction.callback_last_attempt_at.is_(None),
            Transaction.callback_last_attempt_at < cooldown_cutoff,
        ))
        .update({"callback_last_attempt_at": now}, synchronize_session=False)
    )
    db.session.commit()

    if claimed_rows == 0:
        # Nothing to do: not success / no order id yet / already sent /
        # already attempted 10 times / someone else just claimed it.
        return

    # The bulk UPDATE above doesn't update this session's in-memory copy
    # -- re-fetch to read the real current values before using them.
    transaction = Transaction.query.filter_by(id=transaction_id).first()

    if not current_app.config.get("HUBTEL_CALLBACK_ENABLED"):
        logger.info(
            "HUBTEL_CALLBACK_ENABLED is false -- skipping the final callback for transaction %s", transaction_id,
        )
        return

    body = {
        "SessionId": transaction.hubtel_session_id,
        "OrderId": transaction.hubtel_order_id,
        "ServiceStatus": "success",
        "MetaData": None,
    }

    try:
        if current_app.config.get("HUBTEL_MODE") == "fake":
            logger.info("HUBTEL_MODE=fake -- logging the final callback instead of sending it: %s", body)
        else:
            response = requests.post(
                current_app.config["HUBTEL_FINAL_CALLBACK_URL"], json=body, timeout=CALLBACK_TIMEOUT_SECONDS,
            )
            if not (200 <= response.status_code < 300):
                raise HubtelError(f"Hubtel's final callback endpoint returned HTTP {response.status_code}")
    except Exception as error:
        transaction = Transaction.query.filter_by(id=transaction_id).first()
        transaction.callback_attempts += 1
        # Safe message only -- never the exception's full text, which
        # could (in principle) echo back request details.
        transaction.callback_last_error = f"{type(error).__name__}: could not send the final callback"
        db.session.commit()
        return

    transaction.callback_sent_at = now
    db.session.commit()
