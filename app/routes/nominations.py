from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.category import Category
from app.models.nomination import Nomination
from app.utils import normalize_phone

nominations_bp = Blueprint("nominations", __name__, url_prefix="/api/nominations")


@nominations_bp.post("")
def create_nomination():
    data = request.get_json(silent=True) or {}

    category_id = data.get("category_id")
    nominee_name = (data.get("nominee_name") or "").strip()
    nominator_name = (data.get("nominator_name") or "").strip()

    if not category_id:
        return jsonify(error="category_id is required"), 400

    if not nominee_name:
        return jsonify(error="nominee_name is required"), 400

    if not nominator_name:
        return jsonify(error="nominator_name is required"), 400

    category = Category.query.get(category_id)
    if category is None or not category.is_active:
        return jsonify(error="category does not exist or is not active"), 400

    nominee_phone = normalize_phone(data.get("nominee_phone"))
    if nominee_phone is None:
        return jsonify(error="nominee_phone must be in the format 0XXXXXXXXX, 233XXXXXXXXX or +233XXXXXXXXX"), 400

    nominator_phone = normalize_phone(data.get("nominator_phone"))
    if nominator_phone is None:
        return jsonify(error="nominator_phone must be in the format 0XXXXXXXXX, 233XXXXXXXXX or +233XXXXXXXXX"), 400

    # status is always "pending" on creation, regardless of what the request sends.
    nomination = Nomination(
        category_id=category_id,
        nominee_name=nominee_name,
        nominee_phone=nominee_phone,
        nominator_name=nominator_name,
        nominator_phone=nominator_phone,
        status="pending",
    )
    db.session.add(nomination)
    db.session.commit()

    return jsonify(nomination.to_dict()), 201


@nominations_bp.get("/<int:nomination_id>")
def get_nomination(nomination_id):
    nomination = Nomination.query.get(nomination_id)
    if nomination is None:
        return jsonify(error="nomination not found"), 404

    return jsonify(nomination.to_dict())
