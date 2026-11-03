from flask import Blueprint, jsonify, request

from app.auth_utils import admin_required
from app.models.audit_log import AuditLog

audit_bp = Blueprint("audit", __name__, url_prefix="/api/audit-log")


@audit_bp.get("")
@admin_required
def list_audit_log():
    query = AuditLog.query

    action = request.args.get("action")
    if action:
        query = query.filter_by(action=action)

    logs = query.order_by(AuditLog.created_at.desc()).limit(100).all()
    return jsonify([log.to_dict() for log in logs])
