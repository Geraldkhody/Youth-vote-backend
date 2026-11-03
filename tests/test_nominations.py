def valid_payload(category_id, **overrides):
    payload = {
        "category_id": category_id,
        "nominee_name": "Ama Owusu",
        "nominee_phone": "0241234567",
        "nominator_name": "Kofi Mensah",
        "nominator_phone": "0551234567",
    }
    payload.update(overrides)
    return payload


def test_valid_nomination_saves_as_pending(client, active_category):
    response = client.post("/api/nominations", json=valid_payload(active_category, status="approved"))

    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "pending"  # status from the request is ignored
    assert data["nominee_phone"] == "233241234567"
    assert data["nominator_phone"] == "233551234567"


def test_rejects_inactive_category(client, inactive_category):
    response = client.post("/api/nominations", json=valid_payload(inactive_category))

    assert response.status_code == 400
    assert "category" in response.get_json()["error"]


def test_rejects_missing_category(client):
    response = client.post("/api/nominations", json=valid_payload(999999))

    assert response.status_code == 400
    assert "category" in response.get_json()["error"]


def test_normalizes_each_phone_format(client, active_category):
    for raw, expected in [
        ("0241234567", "233241234567"),
        ("233241234567", "233241234567"),
        ("+233241234567", "233241234567"),
    ]:
        response = client.post("/api/nominations", json=valid_payload(active_category, nominee_phone=raw))
        assert response.status_code == 201
        assert response.get_json()["nominee_phone"] == expected


def test_rejects_invalid_phone(client, active_category):
    response = client.post("/api/nominations", json=valid_payload(active_category, nominee_phone="12345"))

    assert response.status_code == 400
    assert "phone" in response.get_json()["error"]


def test_rejects_empty_name(client, active_category):
    response = client.post("/api/nominations", json=valid_payload(active_category, nominee_name="   "))

    assert response.status_code == 400
    assert "nominee_name" in response.get_json()["error"]


def test_get_nomination(client, active_category):
    created = client.post("/api/nominations", json=valid_payload(active_category)).get_json()

    response = client.get(f"/api/nominations/{created['id']}")

    assert response.status_code == 200
    assert response.get_json()["id"] == created["id"]
