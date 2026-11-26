import random
import string
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.nominee import Nominee
from app.models.transaction import Transaction
from app.models.vote import Vote
from app.models.voting_settings import get_settings
from app.services.pricing import calculate_vote_amount
from app.services.voting_status import is_voting_open

# No audit rows are written in this file. log_audit() (app/services/audit.py)
# is for admin actions -- there is no admin here, just a voter paying and
# Hubtel confirming it. Those system-initiated events are already logged by
# the transactions table itself (status, needs_review, provider_payload,
# confirmed_at), so nothing here needs a second, separate log.

MAX_REFERENCE_ATTEMPTS = 5
REFERENCE_LENGTH = 12
REFERENCE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_reference():
    """"V" plus 12 random uppercase letters/digits, e.g. "VAB12CD34EF56".

    Random (not sequential) for the same reason nominee codes are random:
    it stops anyone guessing how many transactions exist, or guessing
    someone else's reference.
    """
    suffix = "".join(random.choices(REFERENCE_ALPHABET, k=REFERENCE_LENGTH))
    return f"V{suffix}"


def _naive_utc_now():
    """The current time as naive UTC, matching how VotingSettings' dates
    are stored (see app/services/voting_settings.py for why)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _lookup_transaction_for_update(identifier):
    """Find a transaction by id, reference, or hubtel_session_id, and lock
    its row with SELECT ... FOR UPDATE so nothing else can change it until
    this database transaction commits or rolls back.

    This lock is what makes record_successful_payment() safe when two
    confirmations for the same payment arrive at (almost) the same time:
    whichever request gets here first holds the row lock and finishes its
    whole decision (check status, maybe create a Vote, commit) before the
    second request's SELECT ... FOR UPDATE is even allowed to return. By
    the time the second request reads the row, it already sees the first
    request's result.
    """
    query = Transaction.query.with_for_update()

    if isinstance(identifier, int):
        return query.filter_by(id=identifier).first()

    transaction = query.filter_by(reference=identifier).first()
    if transaction is None:
        transaction = query.filter_by(hubtel_session_id=identifier).first()
    return transaction


def create_pending_transaction(nominee_id, phone, quantity, channel, hubtel_session_id=None, now=None):
    """Create a new 'pending' transaction for a vote purchase.

    Refuses (raises ValueError) if voting isn't open right now, the
    nominee doesn't exist or isn't active, or the quantity is invalid (see
    calculate_vote_amount for exactly what counts as invalid).

    Reads the CURRENT fee from VotingSettings and freezes it onto the
    transaction as unit_fee_pesewas. A later change to the fee in the
    admin settings must never retroactively change what an
    already-created transaction is worth -- that's why the fee lives on
    the transaction too, not just in VotingSettings.
    """
    now = now if now is not None else _naive_utc_now()

    settings = get_settings()
    if not is_voting_open(settings, now):
        raise ValueError("voting is not open")

    nominee = Nominee.query.get(nominee_id)
    if nominee is None or not nominee.is_active:
        raise ValueError("nominee not found or not active")

    # Also validates quantity (whole number, at least 1, no overflow).
    amount_pesewas = calculate_vote_amount(quantity, settings.vote_fee_pesewas)

    transaction = Transaction(
        reference=_generate_reference(),
        channel=channel,
        hubtel_session_id=hubtel_session_id,
        nominee_id=nominee_id,
        phone=phone,
        quantity=quantity,
        unit_fee_pesewas=settings.vote_fee_pesewas,
        amount_pesewas=amount_pesewas,
        status="pending",
    )
    db.session.add(transaction)

    # The reference is random, so a collision is extremely unlikely but
    # not impossible -- retry a few times with a fresh reference rather
    # than letting a rare collision fail the whole request.
    for attempt in range(MAX_REFERENCE_ATTEMPTS):
        try:
            db.session.commit()
            return transaction
        except IntegrityError:
            db.session.rollback()
            if attempt == MAX_REFERENCE_ATTEMPTS - 1:
                raise
            transaction.reference = _generate_reference()
            db.session.add(transaction)

    raise RuntimeError("could not generate a unique transaction reference")  # pragma: no cover


def record_successful_payment(identifier, paid_amount_pesewas, provider_total_pesewas=None, provider_payload=None, now=None):
    """Confirm a payment and, if everything checks out, create its Vote.

    THIS IS THE ONLY FUNCTION IN THE WHOLE CODEBASE THAT CREATES A VOTE.

    identifier can be a transaction id (int), a reference, or a
    hubtel_session_id -- whichever the caller has on hand.

    All of this happens after locking the transaction row (see
    _lookup_transaction_for_update), so two calls for the same payment
    arriving at the same time can't both create a vote:

    - Already 'success': nothing to do. Returned as-is. This is what makes
      a duplicate confirmation (Hubtel retrying, or us double-processing)
      completely harmless -- calling this twice has the same effect as
      calling it once.
    - 'failed' or 'cancelled': a confirmation shouldn't be arriving for a
      transaction we already gave up on. No vote is created; the
      transaction is flagged needs_review so a human can look at why.
    - Wrong amount: if what was actually paid doesn't match what this
      transaction was supposed to cost, no vote is created either --
      flagged needs_review instead, with the mismatch written down.
    - Otherwise: mark it 'success', stamp confirmed_at, and create exactly
      one Vote with the transaction's quantity.

    A payment can legitimately arrive after voting has closed -- the
    transaction was only ever created while voting was open
    (create_pending_transaction already checked that when the voter
    started paying), so the voter acted in good faith before the
    deadline. The vote must still count even if Hubtel's confirmation
    shows up a bit late.

    This function never calls any external service (so nothing here can
    block on a network call while holding the row lock), and commits as
    soon as the outcome is decided -- never doing extra work, or holding
    the lock, any longer than it has to.
    """
    now = now if now is not None else _naive_utc_now()

    transaction = _lookup_transaction_for_update(identifier)
    if transaction is None:
        raise ValueError(f"transaction not found for identifier: {identifier!r}")

    if transaction.status == "success":
        db.session.commit()  # releases the row lock; nothing to change
        return transaction

    if transaction.status in ("failed", "cancelled"):
        transaction.needs_review = True
        transaction.review_reason = (
            f"payment confirmation received for a transaction already marked '{transaction.status}'"
        )
        db.session.commit()
        return transaction

    if paid_amount_pesewas != transaction.amount_pesewas:
        transaction.needs_review = True
        transaction.review_reason = (
            f"paid amount {paid_amount_pesewas} does not match the expected amount {transaction.amount_pesewas}"
        )
        db.session.commit()
        return transaction

    transaction.status = "success"
    transaction.confirmed_at = now
    transaction.provider_total_pesewas = provider_total_pesewas
    transaction.provider_payload = provider_payload

    vote = Vote(transaction_id=transaction.id, nominee_id=transaction.nominee_id, quantity=transaction.quantity)
    db.session.add(vote)

    try:
        db.session.commit()
    except IntegrityError:
        # Belt and braces: the row lock above should already make this
        # unreachable, but if it's ever bypassed, the UNIQUE constraint on
        # votes.transaction_id is the real guarantee against a double
        # vote. Treat hitting it exactly like the "already success" case.
        db.session.rollback()
        transaction = Transaction.query.filter_by(id=transaction.id).first()

    return transaction


def mark_payment_failed(identifier, reason, provider_payload=None):
    """Mark a 'pending' transaction as 'failed'. Never changes a
    transaction that's already 'success' -- once a vote has been
    recorded, nothing here can undo it."""
    transaction = _lookup_transaction_for_update(identifier)
    if transaction is None:
        raise ValueError(f"transaction not found for identifier: {identifier!r}")

    if transaction.status == "pending":
        transaction.status = "failed"
        transaction.review_reason = reason
        if provider_payload is not None:
            transaction.provider_payload = provider_payload

    db.session.commit()
    return transaction


def mark_payment_cancelled(identifier):
    """Mark a 'pending' transaction as 'cancelled'. Never changes a
    transaction that's already 'success'."""
    transaction = _lookup_transaction_for_update(identifier)
    if transaction is None:
        raise ValueError(f"transaction not found for identifier: {identifier!r}")

    if transaction.status == "pending":
        transaction.status = "cancelled"

    db.session.commit()
    return transaction


def get_nominee_vote_total(nominee_id):
    """Total votes recorded for a nominee (sum of Vote.quantity), or 0 if
    there are none yet."""
    total = (
        db.session.query(db.func.coalesce(db.func.sum(Vote.quantity), 0))
        .filter_by(nominee_id=nominee_id)
        .scalar()
    )
    return int(total)
