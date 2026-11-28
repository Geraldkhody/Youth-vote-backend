from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from app.auth_utils import admin_required
from app.models.transaction import Transaction
from app.services.pricing import format_cedis

admin_transactions_bp = Blueprint("admin_transactions", __name__, url_prefix="/api/admin")

# How long after fulfilment a 'success' transaction with no callback sent
# counts as overdue for the ?callback_overdue=1 filter -- half of
# HUBTEL_CALLBACK_DEADLINE_MINUTES (app/services/hubtel_fulfilment.py),
# so it flags trouble well before Hubtel's real one-hour cutoff.
CALLBACK_OVERDUE_AFTER_MINUTES = 30


def _mask_phone(phone):
    """Keep only the last 3 digits, same convention as the Hubtel
    request log (app/services/hubtel.py)."""
    if not phone or len(phone) <= 3:
        return phone
    return "*" * (len(phone) - 3) + phone[-3:]


def _minutes_since_fulfilment(transaction, now):
    if transaction.fulfilment_received_at is None:
        return None
    return int((now - transaction.fulfilment_received_at).total_seconds() // 60)


def _to_summary(transaction, now):
    # No provider_payload, no hubtel_order_id, nothing beyond what an
    # admin reviewing payments actually needs -- see the route docstring.
    nominee = transaction.nominee
    return {
        "reference": transaction.reference,
        "nominee_code": nominee.code if nominee else None,
        "nominee_name": nominee.full_name if nominee else None,
        "quantity": transaction.quantity,
        "amount_cedis": format_cedis(transaction.amount_pesewas),
        "status": transaction.status,
        "needs_review": transaction.needs_review,
        "review_reason": transaction.review_reason,
        "last_status_outcome": transaction.last_status_outcome,
        "last_status_note": transaction.last_status_note,
        "callback_sent_at": transaction.callback_sent_at.isoformat() if transaction.callback_sent_at else None,
        "callback_attempts": transaction.callback_attempts,
        "created_at": transaction.created_at.isoformat(),
        "phone": _mask_phone(transaction.phone),
        "minutes_since_fulfilment": _minutes_since_fulfilment(transaction, now),
    }


@admin_transactions_bp.get("/transactions")
@admin_required
def list_transactions():
    """Latest 100 transactions, newest first. Optional ?status=,
    ?needs_review= and ?callback_overdue= filters. No raw payloads and no
    Hubtel credentials -- just enough for an admin to see what's happened
    and spot anything flagged for review."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    query = Transaction.query

    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)

    needs_review = request.args.get("needs_review")
    if needs_review is not None:
        query = query.filter_by(needs_review=needs_review.lower() in ("1", "true", "yes"))

    callback_overdue = request.args.get("callback_overdue")
    if callback_overdue is not None and callback_overdue.lower() in ("1", "true", "yes"):
        overdue_cutoff = now - timedelta(minutes=CALLBACK_OVERDUE_AFTER_MINUTES)
        query = (
            query.filter(Transaction.status == "success")
            .filter(Transaction.callback_sent_at.is_(None))
            .filter(Transaction.fulfilment_received_at.isnot(None))
            .filter(Transaction.fulfilment_received_at < overdue_cutoff)
        )

    transactions = query.order_by(Transaction.created_at.desc()).limit(100).all()
    return jsonify([_to_summary(transaction, now) for transaction in transactions])
