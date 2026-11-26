import os
from dotenv import load_dotenv
from urllib.parse import quote_plus

# Load variables from the .env file into the environment so os.environ.get() can see them.
load_dotenv()


class Config:
    """App settings, read from environment variables (which come from .env)."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    # The secret segment of the Hubtel USSD webhook URLs (e.g.
    # /api/hubtel/<HUBTEL_PATH_TOKEN>/interaction). Must be at least 24
    # characters, or the Hubtel routes are not registered at all -- see
    # create_app() in app/__init__.py.
    HUBTEL_PATH_TOKEN = os.environ.get("HUBTEL_PATH_TOKEN", "")

    # Hubtel's transaction status-check API (app/providers/hubtel.py).
    # Never log or return HUBTEL_API_ID / HUBTEL_API_SECRET -- they're the
    # credentials used to build the Basic auth header for that call.
    HUBTEL_COLLECTION_ACCOUNT = os.environ.get("HUBTEL_COLLECTION_ACCOUNT", "")
    HUBTEL_API_ID = os.environ.get("HUBTEL_API_ID", "")
    HUBTEL_API_SECRET = os.environ.get("HUBTEL_API_SECRET", "")
    HUBTEL_STATUS_BASE_URL = os.environ.get("HUBTEL_STATUS_BASE_URL", "https://api-txnstatus.hubtel.com")

    # The final callback Hubtel asks us to send once a transaction is
    # fulfilled (see app/services/hubtel_fulfilment.py).
    HUBTEL_FINAL_CALLBACK_URL = os.environ.get("HUBTEL_FINAL_CALLBACK_URL", "https://gs-callback.hubtel.com:9055/callback")
    # Off by default so a misconfigured dev/staging box can never spam
    # Hubtel's real callback endpoint. Must be explicitly turned on.
    HUBTEL_CALLBACK_ENABLED = os.environ.get("HUBTEL_CALLBACK_ENABLED", "false").lower() == "true"

    # "fake" mode (local/dev only -- see create_app()'s startup check)
    # makes the status check always report "paid" with the exact expected
    # amount, and only logs the final callback instead of sending it, so
    # the whole fulfilment flow can be exercised without a real Hubtel
    # account.
    HUBTEL_MODE = os.environ.get("HUBTEL_MODE", "live")
    APP_ENV = os.environ.get("APP_ENV", "development")

    # Deployed frontend origin(s) allowed to call this API, comma-separated.
    FRONTEND_ORIGINS = [
        origin.strip()
        for origin in os.environ.get("FRONTEND_ORIGIN", "https://hsccawards.vercel.app").split(",")
        if origin.strip()
    ]

    # We don't need SQLAlchemy's change-tracking feature, and it just uses extra memory.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session cookie settings (the admin login session).
    SESSION_COOKIE_HTTPONLY = True  # JavaScript can't read the cookie.
    # "Lax" works for local dev, where the Vite proxy makes requests same-origin.
    # The deployed frontend is on a different domain (cross-site), and browsers
    # only send a cross-site cookie back when it's SameSite=None + Secure.
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    # Secure cookies only work over HTTPS. Locally we run plain HTTP (XAMPP),
    # so this defaults to False and should be set to True in production.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "False").lower() == "true"

    # Database pieces, read individually so each can have a sane default.
    DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
    DB_PORT = os.environ.get("DB_PORT", "3306")
    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_NAME = os.environ.get("DB_NAME", "youth_vote")

    # PyMySQL is the driver; charset=utf8mb4 + utf8mb4_unicode_ci works the same
    # on both MariaDB (XAMPP, dev) and MySQL (production), so we never use
    # anything database-specific here.
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        f"?charset=utf8mb4"
    )
