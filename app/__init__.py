from flask import Flask, jsonify
from sqlalchemy import text

from config import Config
from app.extensions import db, migrate, cors


def create_app(config_overrides=None):
    """App factory: builds and configures the Flask app, then returns it.

    Using a factory (instead of a module-level `app = Flask(__name__)`) makes
    it easy to create fresh app instances for testing later, and avoids
    import-order problems with the database extensions.

    config_overrides lets tests swap in a different database (e.g. SQLite in
    memory) without touching the real .env settings.
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    # "fake" Hubtel mode (always reports payments as "paid", never really
    # calls Hubtel) must never run in production -- that would mean every
    # vote gets recorded as paid without anyone actually paying.
    if app.config.get("HUBTEL_MODE") == "fake" and app.config.get("APP_ENV") == "production":
        raise RuntimeError("Refusing to start: HUBTEL_MODE=fake with APP_ENV=production.")

    # Hook up the database extensions to this specific app instance.
    db.init_app(app)
    migrate.init_app(app, db)

    # Allow the deployed frontend to call this API, including the admin
    # session cookie (credentials) for the login-protected routes.
    cors.init_app(app, origins=app.config["FRONTEND_ORIGINS"], supports_credentials=True)

    # Imported here (not at the top of the file) so the models are registered
    # with SQLAlchemy only once create_app() actually runs.
    from app import models  # noqa: F401
    from app.routes.categories import categories_bp, admin_categories_bp
    from app.routes.nominations import nominations_bp
    from app.routes.review import review_bp
    from app.routes.auth import auth_bp
    from app.routes.nominees import nominees_bp
    from app.routes.audit import audit_bp
    from app.routes.hubtel_admin import admin_hubtel_bp
    from app.routes.voting_settings import voting_bp, admin_voting_bp
    from app.routes.transactions_admin import admin_transactions_bp

    app.register_blueprint(categories_bp)
    app.register_blueprint(admin_categories_bp)
    app.register_blueprint(nominations_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(nominees_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(admin_hubtel_bp)
    app.register_blueprint(voting_bp)
    app.register_blueprint(admin_voting_bp)
    app.register_blueprint(admin_transactions_bp)

    # Hubtel USSD stub routes (app/routes/hubtel.py) only register when a
    # real path token is configured. Without this, the URL would be
    # predictable (just "/api/hubtel/<anything>/...") and that's the only
    # thing standing between the public internet and these endpoints.
    hubtel_token = app.config.get("HUBTEL_PATH_TOKEN", "")
    if len(hubtel_token) >= 24:
        from app.routes.hubtel import hubtel_bp
        app.register_blueprint(hubtel_bp)
    else:
        app.logger.warning(
            "HUBTEL_PATH_TOKEN is missing or shorter than 24 characters -- "
            "Hubtel USSD routes were not registered."
        )

    from app.cli import register_cli
    register_cli(app)

    @app.get("/api/health")
    def health():
        try:
            # Simplest possible query, just to prove the connection works.
            db.session.execute(text("SELECT 1"))
            return jsonify(status="ok", database="connected")
        except Exception as error:
            return jsonify(status="error", database="disconnected", message=str(error)), 500

    return app
