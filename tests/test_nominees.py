def test_public_list_shows_only_active_nominees(client, logged_in_client, make_active_nominee):
    active = make_active_nominee(nominee_name="Active One")
    inactive = make_active_nominee(nominee_name="Inactive One")
    logged_in_client.post(f"/api/nominees/{inactive['id']}/deactivate", json={"reason": "Withdrew"})

    response = client.get("/api/nominees")

    assert response.status_code == 200
    names = [n["full_name"] for n in response.get_json()]
    assert "Active One" in names
    assert "Inactive One" not in names


def test_public_list_hides_phone_numbers(client, make_active_nominee):
    make_active_nominee()

    response = client.get("/api/nominees")

    nominee = response.get_json()[0]
    assert "phone" not in nominee
    assert set(nominee.keys()) == {"id", "code", "full_name", "category_id"}


def test_detail_endpoint_requires_login(client, make_active_nominee):
    nominee = make_active_nominee()
    # make_active_nominee logs the shared test client in to approve the
    # nomination, so log back out before checking the logged-out behavior.
    client.post("/api/auth/logout")

    response = client.get(f"/api/nominees/{nominee['id']}")

    assert response.status_code == 401


def test_detail_endpoint_works_when_logged_in(logged_in_client, make_active_nominee):
    nominee = make_active_nominee()

    response = logged_in_client.get(f"/api/nominees/{nominee['id']}")

    assert response.status_code == 200
    assert response.get_json()["phone"] == "233241234567"


def test_deactivation_requires_reason(logged_in_client, make_active_nominee):
    nominee = make_active_nominee()

    response = logged_in_client.post(f"/api/nominees/{nominee['id']}/deactivate", json={})

    assert response.status_code == 400
    assert "reason" in response.get_json()["error"]


def test_deactivating_twice_is_refused(logged_in_client, make_active_nominee):
    nominee = make_active_nominee()
    logged_in_client.post(f"/api/nominees/{nominee['id']}/deactivate", json={"reason": "Withdrew"})

    response = logged_in_client.post(f"/api/nominees/{nominee['id']}/deactivate", json={"reason": "Again"})

    assert response.status_code == 400
    assert "already inactive" in response.get_json()["error"]


def test_deactivated_nominee_still_exists_but_hidden_from_public_list(client, logged_in_client, make_active_nominee):
    nominee = make_active_nominee()
    logged_in_client.post(f"/api/nominees/{nominee['id']}/deactivate", json={"reason": "Withdrew"})

    public_response = client.get("/api/nominees")
    assert nominee["id"] not in [n["id"] for n in public_response.get_json()]

    admin_response = logged_in_client.get(f"/api/nominees/{nominee['id']}")
    assert admin_response.status_code == 200
    assert admin_response.get_json()["is_active"] is False
    assert admin_response.get_json()["deactivation_reason"] == "Withdrew"


def test_edit_name_and_phone(logged_in_client, make_active_nominee):
    nominee = make_active_nominee()

    response = logged_in_client.patch(f"/api/nominees/{nominee['id']}", json={
        "full_name": "Efua Asante-Mensah",
        "phone": "+233501234567",
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data["full_name"] == "Efua Asante-Mensah"
    assert data["phone"] == "233501234567"  # normalised, same as nominations


def test_edit_refuses_empty_name(logged_in_client, make_active_nominee):
    nominee = make_active_nominee()

    response = logged_in_client.patch(f"/api/nominees/{nominee['id']}", json={"full_name": "   "})

    assert response.status_code == 400
    assert "full_name" in response.get_json()["error"]


def test_edit_refuses_inactive_nominee(logged_in_client, make_active_nominee):
    nominee = make_active_nominee()
    logged_in_client.post(f"/api/nominees/{nominee['id']}/deactivate", json={"reason": "Withdrew"})

    response = logged_in_client.patch(f"/api/nominees/{nominee['id']}", json={"full_name": "New Name"})

    assert response.status_code == 400
    assert "inactive" in response.get_json()["error"]
