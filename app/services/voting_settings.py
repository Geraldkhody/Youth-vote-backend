from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.voting_settings import get_settings
from app.services.audit import log_audit


def cedis_to_pesewas(value):
    """Convert a GH₵ amount (e.g. "1.50", 1.5, or 150) to whole pesewas.

    Uses Decimal (built from the value's string form) instead of float
    math, so "1.50" always becomes exactly 150 -- never 149 or 151 from a
    rounding error.
    """
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("vote_fee_cedis must be a number")

    pesewas = decimal_value * 100
    if pesewas != pesewas.to_integral_value():
        raise ValueError("vote_fee_cedis must not have more than 2 decimal places")

    return int(pesewas)


def _parse_utc_datetime(value):
    """Parse an ISO datetime string (or pass through a datetime) as UTC.

    A string with no timezone offset is assumed to already be UTC (the
    only timezone this system ever stores). A string with an offset, or a
    "Z" suffix, is converted to UTC.

    Returns a naive datetime (no tzinfo) representing that UTC instant --
    the database column is a plain DATETIME with no timezone of its own,
    and storing a naive value everywhere keeps every datetime this system
    compares (settings, "now", etc.) on the same footing.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def update_voting_settings(vote_fee_cedis=None, voting_opens_at=None, voting_closes_at=None, admin_id=None):
    """Update one or more voting settings fields. Each argument is only
    applied if it was actually passed, so a PATCH can send just one field.

    Raises ValueError for bad input: a fee of 0 or less, or a closing time
    that isn't after the opening time.

    The fee can be changed at any time, including while voting is open --
    a transaction already in progress has its own fee saved on itself
    separately, so changing this setting never retroactively changes a
    transaction that already exists.
    """
    settings = get_settings()
    changes = {}

    new_fee = settings.vote_fee_pesewas
    if vote_fee_cedis is not None:
        new_fee = cedis_to_pesewas(vote_fee_cedis)
        if new_fee <= 0:
            raise ValueError("vote_fee_cedis must be greater than 0")

    new_opens_at = settings.voting_opens_at
    if voting_opens_at is not None:
        new_opens_at = _parse_utc_datetime(voting_opens_at)

    new_closes_at = settings.voting_closes_at
    if voting_closes_at is not None:
        new_closes_at = _parse_utc_datetime(voting_closes_at)

    if new_opens_at is not None and new_closes_at is not None and new_closes_at <= new_opens_at:
        raise ValueError("voting_closes_at must be after voting_opens_at")

    if new_fee != settings.vote_fee_pesewas:
        changes["vote_fee_pesewas"] = {"before": settings.vote_fee_pesewas, "after": new_fee}
        settings.vote_fee_pesewas = new_fee

    if new_opens_at != settings.voting_opens_at:
        changes["voting_opens_at"] = {
            "before": settings.voting_opens_at.isoformat() if settings.voting_opens_at else None,
            "after": new_opens_at.isoformat() if new_opens_at else None,
        }
        settings.voting_opens_at = new_opens_at

    if new_closes_at != settings.voting_closes_at:
        changes["voting_closes_at"] = {
            "before": settings.voting_closes_at.isoformat() if settings.voting_closes_at else None,
            "after": new_closes_at.isoformat() if new_closes_at else None,
        }
        settings.voting_closes_at = new_closes_at

    if changes:
        settings.updated_by = admin_id
        log_audit("voting_settings.update", "voting_settings", settings.id, changes, admin_id=admin_id)

    db.session.commit()
    return settings


def pause_voting(admin_id=None):
    settings = get_settings()
    if not settings.voting_paused:
        settings.voting_paused = True
        settings.updated_by = admin_id
        log_audit(
            "voting_settings.pause", "voting_settings", settings.id,
            {"voting_paused": {"before": False, "after": True}}, admin_id=admin_id,
        )
    db.session.commit()
    return settings


def resume_voting(admin_id=None):
    settings = get_settings()
    if settings.voting_paused:
        settings.voting_paused = False
        settings.updated_by = admin_id
        log_audit(
            "voting_settings.resume", "voting_settings", settings.id,
            {"voting_paused": {"before": True, "after": False}}, admin_id=admin_id,
        )
    db.session.commit()
    return settings
