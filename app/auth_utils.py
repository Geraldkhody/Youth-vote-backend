from functools import wraps

from flask import jsonify, session


def admin_required(view_func):
    """Decorator for routes that need a logged-in admin.

    Checks for "admin_id" in the Flask session (set by /api/auth/login).
    Returns 401 with a clear message if nobody is logged in.
    """

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return jsonify(error="authentication required"), 401
        return view_func(*args, **kwargs)

    return wrapper
