import os
from dotenv import load_dotenv

# Load variables from the .env file into the environment so os.environ.get() can see them.
load_dotenv()


class Config:
    """App settings, read from environment variables (which come from .env)."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

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
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        f"?charset=utf8mb4"
    )
