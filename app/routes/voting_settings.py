from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from app.auth_utils import admin_required
from app.models.voting_settings import _isoformat_utc, get_settings
from app.services.pricing import format_cedis
from app.services.voting_settings import pause_voting, resume_voting, update_voting_settings
from app.services.voting_status import is_voting_open, voting_state

# Public: GET /api/voting/status
voting_bp = Blueprint("voting_status", __name__, url_prefix="/api/voting")

# Admin-only: /api/admin/voting-settings, /api/admin/voting/pause, /resume
admin_voting_bp = Blueprint("admin_voting", __name__, url_prefix="/api/admin")


@voting_bp.get("/status")
def public_voting_status():
    """Public voting status. Only what a voter needs to know -- no admin
    ids or other internal fields."""
    settings = get_settings()
    # Naive UTC "now", to match how voting_opens_at/voting_closes_at are
    # stored (see _parse_utc_datetime in app/services/voting_settings.py).
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    return jsonify(
        state=voting_state(settings, now),
        is_open=is_voting_open(settings, now),
        vote_fee_pesewas=settings.vote_fee_pesewas,
        vote_fee_display=format_cedis(settings.vote_fee_pesewas),
        voting_opens_at=_isoformat_utc(settings.voting_opens_at),
        voting_closes_at=_isoformat_utc(settings.voting_closes_at),
    )


@admin_voting_bp.get("/voting-settings")
@admin_required
def get_voting_settings():
    return jsonify(get_settings().to_dict())


@admin_voting_bp.patch("/voting-settings")
@admin_required
def patch_voting_settings():
    data = request.get_json(silent=True) or {}

    try:
        settings = update_voting_settings(
            vote_fee_cedis=data.get("vote_fee_cedis"),
            voting_opens_at=data.get("voting_opens_at"),
            voting_closes_at=data.get("voting_closes_at"),
            admin_id=g.admin_id,
        )
    except ValueError as error:
        return jsonify(error=str(error)), 400

    return jsonify(settings.to_dict())


@admin_voting_bp.post("/voting/pause")
@admin_required
def pause_voting_route():
    settings = pause_voting(admin_id=g.admin_id)
    return jsonify(settings.to_dict())


@admin_voting_bp.post("/voting/resume")
@admin_required
def resume_voting_route():
    settings = resume_voting(admin_id=g.admin_id)
    return jsonify(settings.to_dict())
