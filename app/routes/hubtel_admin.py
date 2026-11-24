from flask import Blueprint, jsonify

from app.auth_utils import admin_required
from app.models.hubtel_log import HubtelLog

admin_hubtel_bp = Blueprint("admin_hubtel", __name__, url_prefix="/api/admin")


@admin_hubtel_bp.get("/hubtel-log")
@admin_required
def list_hubtel_log():
    logs = HubtelLog.query.order_by(HubtelLog.received_at.desc()).limit(50).all()
    return jsonify([log.to_dict() for log in logs])
