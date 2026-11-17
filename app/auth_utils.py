from functools import wraps

from flask import current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# How long a login token stays valid. Admins have to log in again after this.
TOKEN_MAX_AGE_SECONDS = 2 * 24 * 60 * 60  # 7 days


def _serializer():
    # Signed with the app's SECRET_KEY, so a token can't be forged or
    # tampered with without knowing it. Stateless: nothing is stored in the
    # database, the signature itself is what makes it trustworthy.
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="admin-auth-token")


def generate_admin_token(admin_id):
    """Create a signed, timestamped token for an admin who just logged in.

    The frontend stores this (e.g. in localStorage) and sends it back as
    "Authorization: Bearer <token>" on every admin request, instead of
    relying on a session cookie -- cookies don't reliably cross from a
    Vercel-hosted frontend to this API on mobile browsers that block
    third-party cookies.
    """
    return _serializer().dumps(admin_id)


def get_current_admin_id():
    """Read and verify the admin id from the request's Authorization header.

    Returns None if the header is missing, malformed, expired, or the
    token's signature doesn't check out -- callers treat all of those the
    same way (not logged in).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[len("Bearer "):].strip()
    try:
        return _serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def admin_required(view_func):
    """Decorator for routes that need a logged-in admin.

    Verifies the bearer token from the Authorization header (set by
    /api/auth/login) and stores the admin id on flask.g for the rest of the
    request -- e.g. log_audit() reads it from there. Returns 401 with a
    clear message if the token is missing or invalid.
    """

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        admin_id = get_current_admin_id()
        if not admin_id:
            return jsonify(error="authentication required"), 401
        g.admin_id = admin_id
        return view_func(*args, **kwargs)

    return wrapper
