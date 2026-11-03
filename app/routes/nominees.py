from flask import Blueprint, jsonify, request

from app.auth_utils import admin_required
from app.models.nominee import Nominee
from app.services.nominees import deactivate_nominee, edit_nominee

nominees_bp = Blueprint("nominees", __name__, url_prefix="/api/nominees")


@nominees_bp.get("")
def list_nominees():
    """Public: active nominees only, and never their phone numbers."""
    query = Nominee.query.filter_by(is_active=True)

    category_id = request.args.get("category_id")
    if category_id:
        query = query.filter_by(category_id=category_id)

    nominees = query.order_by(Nominee.code).all()
    return jsonify([nominee.to_public_dict() for nominee in nominees])


@nominees_bp.get("/<int:nominee_id>")
@admin_required
def get_nominee(nominee_id):
    nominee = Nominee.query.get(nominee_id)
    if nominee is None:
        return jsonify(error="nominee not found"), 404

    return jsonify(nominee.to_dict())


@nominees_bp.patch("/<int:nominee_id>")
@admin_required
def update_nominee(nominee_id):
    nominee = Nominee.query.get(nominee_id)
    if nominee is None:
        return jsonify(error="nominee not found"), 404

    data = request.get_json(silent=True) or {}

    try:
        edit_nominee(nominee, full_name=data.get("full_name"), phone=data.get("phone"))
    except ValueError as error:
        return jsonify(error=str(error)), 400

    return jsonify(nominee.to_dict())


@nominees_bp.post("/<int:nominee_id>/deactivate")
@admin_required
def deactivate(nominee_id):
    nominee = Nominee.query.get(nominee_id)
    if nominee is None:
        return jsonify(error="nominee not found"), 404

    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify(error="reason is required"), 400

    try:
        deactivate_nominee(nominee, reason)
    except ValueError as error:
        return jsonify(error=str(error)), 400

    return jsonify(nominee.to_dict())
