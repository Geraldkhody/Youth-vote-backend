from flask import Flask, jsonify
from sqlalchemy import text

from config import Config
from app.extensions import db, migrate


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

    # Hook up the database extensions to this specific app instance.
    db.init_app(app)
    migrate.init_app(app, db)

    # Imported here (not at the top of the file) so the models are registered
    # with SQLAlchemy only once create_app() actually runs.
    from app import models  # noqa: F401
    from app.routes.categories import categories_bp, admin_categories_bp
    from app.routes.nominations import nominations_bp
    from app.routes.review import review_bp
    from app.routes.auth import auth_bp
    from app.routes.nominees import nominees_bp
    from app.routes.audit import audit_bp

    app.register_blueprint(categories_bp)
    app.register_blueprint(admin_categories_bp)
    app.register_blueprint(nominations_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(nominees_bp)
    app.register_blueprint(audit_bp)

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
