from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models.admin_user import AdminUser
from app.services.audit import log_audit

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Always the same message for a wrong email, wrong password, or a
# deactivated admin, so a caller can't tell which one of those happened.
INVALID_CREDENTIALS_MESSAGE = "Invalid email or password"


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    admin = AdminUser.query.filter_by(email=email).first()

    if admin is None or not admin.is_active or not admin.check_password(password):
        return jsonify(error=INVALID_CREDENTIALS_MESSAGE), 401

    session["admin_id"] = admin.id
    log_audit("admin.login", "admin_user", admin.id)
    db.session.commit()
    return jsonify(name=admin.name, email=admin.email)


@auth_bp.post("/logout")
def logout():
    admin_id = session.get("admin_id")
    if admin_id:
        # Log before popping the session, since log_audit reads the admin
        # from the current session.
        log_audit("admin.logout", "admin_user", admin_id)
        db.session.commit()

    session.pop("admin_id", None)
    return jsonify(message="logged out")


@auth_bp.get("/me")
def me():
    admin_id = session.get("admin_id")
    if not admin_id:
        return jsonify(error="authentication required"), 401

    admin = AdminUser.query.get(admin_id)
    if admin is None:
        # Admin was deleted after logging in; treat the session as invalid.
        session.pop("admin_id", None)
        return jsonify(error="authentication required"), 401

    return jsonify(name=admin.name, email=admin.email)
