from app.models.admin_user import AdminUser

INVALID_CREDENTIALS_MESSAGE = "Invalid email or password"


def test_login_success(client, admin_user):
    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "secret123"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["name"] == "Admin User"
    assert data["email"] == "admin@example.com"


def test_wrong_password_refused(client, admin_user):
    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong"})

    assert response.status_code == 401
    assert response.get_json()["error"] == INVALID_CREDENTIALS_MESSAGE


def test_unknown_email_refused_with_same_message(client, admin_user):
    response = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "secret123"})

    assert response.status_code == 401
    assert response.get_json()["error"] == INVALID_CREDENTIALS_MESSAGE


def test_deactivated_admin_refused(client, inactive_admin):
    response = client.post("/api/auth/login", json={"email": "former@example.com", "password": "secret123"})

    assert response.status_code == 401
    assert response.get_json()["error"] == INVALID_CREDENTIALS_MESSAGE


def test_me_returns_401_when_logged_out(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_me_returns_admin_when_logged_in(logged_in_client):
    response = logged_in_client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.get_json()["email"] == "admin@example.com"


def test_logout_clears_session(logged_in_client):
    logged_in_client.post("/api/auth/logout")

    response = logged_in_client.get("/api/auth/me")

    assert response.status_code == 401


def test_password_is_stored_hashed(app, admin_user):
    with app.app_context():
        admin = AdminUser.query.get(admin_user)
        assert admin.password_hash != "secret123"
        assert admin.check_password("secret123") is True
