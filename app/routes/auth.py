from flask import Blueprint, g, jsonify, request

from app.auth_utils import admin_required, generate_admin_token, get_current_admin_id
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

    # No token exists yet for this request to carry, so pass admin_id
    # explicitly rather than relying on log_audit's flask.g lookup.
    log_audit("admin.login", "admin_user", admin.id, admin_id=admin.id)
    db.session.commit()

    token = generate_admin_token(admin.id)
    return jsonify(name=admin.name, email=admin.email, token=token)


@auth_bp.post("/logout")
def logout():
    # Logging out a stateless token is just the client discarding it -- there's
    # nothing server-side to invalidate. We still log who logged out, if the
    # request happens to include a still-valid token.
    admin_id = get_current_admin_id()
    if admin_id:
        log_audit("admin.logout", "admin_user", admin_id, admin_id=admin_id)
        db.session.commit()

    return jsonify(message="logged out")


@auth_bp.get("/me")
@admin_required
def me():
    admin = AdminUser.query.get(g.admin_id)
    if admin is None:
        # Admin was deleted after the token was issued; treat it as invalid.
        return jsonify(error="authentication required"), 401

    return jsonify(name=admin.name, email=admin.email)
