import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def app():
    """A Flask app configured for tests: an in-memory SQLite database.

    Using SQLite in memory (instead of the real MariaDB database) keeps
    tests fast and avoids touching real data. The mysql-specific table
    options on the Category model are simply ignored by SQLite.
    """
    test_app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "TESTING": True,
    })

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def active_category(app):
    """An active category for tests that need a valid category_id."""
    from app.models.category import Category

    with app.app_context():
        category = Category(name="Youth Leader of the Year", code_letter="A", is_active=True)
        db.session.add(category)
        db.session.commit()
        return category.id


@pytest.fixture
def second_active_category(app):
    """A second active category, distinct from active_category, for tests
    that need two different categories (e.g. merge rules)."""
    from app.models.category import Category

    with app.app_context():
        category = Category(name="Sports Star of the Year", code_letter="S", is_active=True)
        db.session.add(category)
        db.session.commit()
        return category.id


@pytest.fixture
def inactive_category(app):
    """An inactive category, to test that nominations reject it."""
    from app.models.category import Category

    with app.app_context():
        category = Category(name="Retired Category", code_letter="B", is_active=False)
        db.session.add(category)
        db.session.commit()
        return category.id


@pytest.fixture
def admin_user(app):
    """An active admin with a known password, for login tests."""
    from app.models.admin_user import AdminUser

    with app.app_context():
        admin = AdminUser(name="Admin User", email="admin@example.com", is_active=True)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()
        return admin.id


@pytest.fixture
def inactive_admin(app):
    """A deactivated admin, to test that login refuses them."""
    from app.models.admin_user import AdminUser

    with app.app_context():
        admin = AdminUser(name="Former Admin", email="former@example.com", is_active=False)
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()
        return admin.id


@pytest.fixture
def logged_in_client(client, admin_user):
    """A test client that has already logged in as the admin_user fixture."""
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": "secret123"})
    return client


@pytest.fixture
def make_pending_nomination(client, active_category):
    """Factory fixture: creates a pending nomination via the real API and
    returns its id, so review tests don't have to repeat the POST body."""

    def _make(category_id=None, nominee_name="Ama Owusu"):
        response = client.post("/api/nominations", json={
            "category_id": category_id or active_category,
            "nominee_name": nominee_name,
            "nominee_phone": "0241234567",
            "nominator_name": "Kofi Mensah",
            "nominator_phone": "0551234567",
        })
        return response.get_json()["id"]

    return _make


@pytest.fixture
def make_active_nominee(logged_in_client, make_pending_nomination):
    """Factory fixture: creates a pending nomination and approves it, so
    tests get back a real, active Nominee (as the approve endpoint returns it)."""

    def _make(category_id=None, nominee_name="Ama Owusu"):
        nomination_id = make_pending_nomination(category_id=category_id, nominee_name=nominee_name)
        response = logged_in_client.post(f"/api/nominations/{nomination_id}/approve")
        return response.get_json()

    return _make
