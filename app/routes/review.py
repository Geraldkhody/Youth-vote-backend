from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.auth_utils import admin_required
from app.extensions import db
from app.models.nomination import Nomination
from app.models.nominee import Nominee
from app.services.audit import log_audit
from app.services.codes import generate_nominee_code
from app.services.nominees import merge_nomination_into_nominee

review_bp = Blueprint("review", __name__, url_prefix="/api/nominations")


@review_bp.get("")
@admin_required
def list_nominations():
    query = Nomination.query

    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)

    category_id = request.args.get("category_id")
    if category_id:
        query = query.filter_by(category_id=category_id)

    nominations = query.order_by(Nomination.created_at).all()
    return jsonify([nomination.to_dict() for nomination in nominations])


@review_bp.post("/<int:nomination_id>/approve")
@admin_required
def approve_nomination(nomination_id):
    nomination = Nomination.query.get(nomination_id)
    if nomination is None:
        return jsonify(error="nomination not found"), 404

    if nomination.status != "pending":
        return jsonify(error=f"only pending nominations can be approved (this one is '{nomination.status}')"), 400

    category = nomination.category

    # Two approvals could land on the same randomly-picked code at nearly
    # the same time: both check the code is free, then both try to save it.
    # The database's unique constraint on (category_id, code) will let only
    # one of them through. If ours loses that race, we just generate a new
    # code and try once more rather than failing the whole request.
    nominee = None
    for attempt in range(2):
        code = generate_nominee_code(category)
        nominee = Nominee(
            category_id=category.id,
            code=code,
            full_name=nomination.nominee_name,
            phone=nomination.nominee_phone,
        )
        db.session.add(nominee)
        db.session.flush()  # assigns nominee.id, without committing yet
        log_audit("nominee.create", "nominee", nominee.id, {"code": nominee.code, "full_name": nominee.full_name})
        try:
            db.session.commit()
            break
        except IntegrityError:
            db.session.rollback()
            nominee = None
            if attempt == 1:  # second attempt also collided; give up with a clear error
                return jsonify(error="could not save nominee: code collision twice in a row"), 500

    nomination.status = "approved"
    nomination.nominee_id = nominee.id
    nomination.reviewed_at = datetime.now(timezone.utc)
    log_audit("nomination.approve", "nomination", nomination.id, {"nominee_id": nominee.id})
    db.session.commit()

    return jsonify(nominee.to_dict()), 201


@review_bp.post("/<int:nomination_id>/reject")
@admin_required
def reject_nomination(nomination_id):
    nomination = Nomination.query.get(nomination_id)
    if nomination is None:
        return jsonify(error="nomination not found"), 404

    if nomination.status != "pending":
        return jsonify(error=f"only pending nominations can be rejected (this one is '{nomination.status}')"), 400

    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify(error="reason is required"), 400

    nomination.status = "rejected"
    nomination.rejection_reason = reason
    nomination.reviewed_at = datetime.now(timezone.utc)
    log_audit("nomination.reject", "nomination", nomination.id, {"reason": reason})
    db.session.commit()

    return jsonify(nomination.to_dict())


@review_bp.post("/<int:nomination_id>/merge")
@admin_required
def merge_nomination(nomination_id):
    nomination = Nomination.query.get(nomination_id)
    if nomination is None:
        return jsonify(error="nomination not found"), 404

    data = request.get_json(silent=True) or {}
    nominee = Nominee.query.get(data.get("nominee_id")) if data.get("nominee_id") else None
    if nominee is None:
        return jsonify(error="nominee not found"), 404

    try:
        merge_nomination_into_nominee(nomination, nominee)
    except ValueError as error:
        return jsonify(error=str(error)), 400

    return jsonify(nomination.to_dict())
