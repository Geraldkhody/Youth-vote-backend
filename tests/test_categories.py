def test_create_category_requires_login(client):
    response = client.post("/api/categories", json={"name": "Youth Leader of the Year", "code_letter": "A"})

    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication required"


def test_create_category(logged_in_client):
    response = logged_in_client.post("/api/categories", json={
        "name": "Youth Leader of the Year",
        "code_letter": "a",  # lowercase on purpose, should be stored uppercase
    })

    assert response.status_code == 201
    data = response.get_json()
    assert data["name"] == "Youth Leader of the Year"
    assert data["code_letter"] == "A"
    assert data["is_active"] is True


def test_reject_duplicate_letter(logged_in_client):
    logged_in_client.post("/api/categories", json={"name": "First", "code_letter": "B"})
    response = logged_in_client.post("/api/categories", json={"name": "Second", "code_letter": "B"})

    assert response.status_code == 400
    assert "already in use" in response.get_json()["error"]


def test_reject_empty_name(logged_in_client):
    response = logged_in_client.post("/api/categories", json={"name": "   ", "code_letter": "C"})

    assert response.status_code == 400
    assert "name" in response.get_json()["error"]


def test_list_only_active_categories(logged_in_client):
    logged_in_client.post("/api/categories", json={"name": "Active One", "code_letter": "D"})
    logged_in_client.post("/api/categories", json={"name": "Active Two", "code_letter": "E"})
    logged_in_client.post("/api/categories", json={"name": "Inactive", "code_letter": "F"})
    logged_in_client.patch("/api/categories/3", json={"is_active": False})

    response = logged_in_client.get("/api/categories")

    assert response.status_code == 200
    names = [category["name"] for category in response.get_json()]
    assert names == ["Active One", "Active Two"]
    assert "Inactive" not in names


def test_admin_list_includes_inactive_categories(logged_in_client):
    logged_in_client.post("/api/categories", json={"name": "Active", "code_letter": "G"})
    logged_in_client.post("/api/categories", json={"name": "Inactive", "code_letter": "H"})
    logged_in_client.patch("/api/categories/2", json={"is_active": False})

    response = logged_in_client.get("/api/admin/categories")

    assert response.status_code == 200
    names = [category["name"] for category in response.get_json()]
    assert names == ["Active", "Inactive"]


def test_admin_list_requires_login(client):
    response = client.get("/api/admin/categories")

    assert response.status_code == 401


def test_edit_name(logged_in_client):
    logged_in_client.post("/api/categories", json={"name": "Old Name", "code_letter": "I"})

    response = logged_in_client.patch("/api/categories/1", json={"name": "New Name"})

    assert response.status_code == 200
    assert response.get_json()["name"] == "New Name"


def test_edit_name_rejects_empty(logged_in_client):
    logged_in_client.post("/api/categories", json={"name": "Old Name", "code_letter": "J"})

    response = logged_in_client.patch("/api/categories/1", json={"name": "   "})

    assert response.status_code == 400
    assert "name" in response.get_json()["error"]


def test_deactivate_hides_from_public_list_but_keeps_it(logged_in_client):
    logged_in_client.post("/api/categories", json={"name": "Retiring", "code_letter": "K"})

    response = logged_in_client.patch("/api/categories/1", json={"is_active": False})
    assert response.status_code == 200
    assert response.get_json()["is_active"] is False

    public_response = logged_in_client.get("/api/categories")
    assert "Retiring" not in [c["name"] for c in public_response.get_json()]

    # Still exists -- there's no delete, only deactivation.
    get_response = logged_in_client.get("/api/categories/1")
    assert get_response.status_code == 200
    assert get_response.get_json()["name"] == "Retiring"


def test_code_letter_change_refused_with_nominations(logged_in_client, make_pending_nomination):
    create_response = logged_in_client.post("/api/categories", json={"name": "Has Nominations", "code_letter": "L"})
    category_id = create_response.get_json()["id"]
    make_pending_nomination(category_id=category_id)

    response = logged_in_client.patch(f"/api/categories/{category_id}", json={"code_letter": "M"})

    assert response.status_code == 400
    assert "nominations or nominees" in response.get_json()["error"]


def test_code_letter_change_allowed_without_nominations_or_nominees(logged_in_client):
    create_response = logged_in_client.post("/api/categories", json={"name": "Fresh Category", "code_letter": "N"})
    category_id = create_response.get_json()["id"]

    response = logged_in_client.patch(f"/api/categories/{category_id}", json={"code_letter": "O"})

    assert response.status_code == 200
    assert response.get_json()["code_letter"] == "O"
