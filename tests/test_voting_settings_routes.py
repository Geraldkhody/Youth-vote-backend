from app.models.audit_log import AuditLog


def test_public_status_works_logged_out(client):
    response = client.get("/api/voting/status")

    assert response.status_code == 200
    body = response.get_json()
    assert body["state"] == "not_scheduled"
    assert body["is_open"] is False
    assert body["vote_fee_pesewas"] == 100
    assert body["vote_fee_display"] == "GH₵1.00"

    # No admin-only fields leak through the public endpoint.
    assert "updated_by" not in body
    assert "id" not in body


def test_admin_get_settings_returns_401_when_logged_out(client):
    response = client.get("/api/admin/voting-settings")
    assert response.status_code == 401


def test_admin_patch_settings_returns_401_when_logged_out(client):
    response = client.patch("/api/admin/voting-settings", json={"vote_fee_cedis": "1.50"})
    assert response.status_code == 401


def test_patch_fee_zero_is_refused(logged_in_client):
    response = logged_in_client.patch("/api/admin/voting-settings", json={"vote_fee_cedis": "0"})
    assert response.status_code == 400


def test_patch_closes_before_opens_is_refused(logged_in_client):
    response = logged_in_client.patch("/api/admin/voting-settings", json={
        "voting_opens_at": "2026-06-02T00:00:00+00:00",
        "voting_closes_at": "2026-06-01T00:00:00+00:00",
    })
    assert response.status_code == 400


def test_patch_fee_in_cedis_stored_as_pesewas(logged_in_client):
    response = logged_in_client.patch("/api/admin/voting-settings", json={"vote_fee_cedis": "1.50"})

    assert response.status_code == 200
    assert response.get_json()["vote_fee_pesewas"] == 150


def test_patch_sets_a_window_and_public_status_reflects_it(logged_in_client, client):
    response = logged_in_client.patch("/api/admin/voting-settings", json={
        "vote_fee_cedis": "2.00",
        "voting_opens_at": "2020-01-01T00:00:00+00:00",
        "voting_closes_at": "2099-01-01T00:00:00+00:00",
    })
    assert response.status_code == 200

    status = client.get("/api/voting/status").get_json()
    assert status["state"] == "open"
    assert status["is_open"] is True
    assert status["vote_fee_pesewas"] == 200


def test_pause_then_resume(logged_in_client, client):
    logged_in_client.patch("/api/admin/voting-settings", json={
        "voting_opens_at": "2020-01-01T00:00:00+00:00",
        "voting_closes_at": "2099-01-01T00:00:00+00:00",
    })

    pause_response = logged_in_client.post("/api/admin/voting/pause")
    assert pause_response.status_code == 200
    assert pause_response.get_json()["voting_paused"] is True
    assert client.get("/api/voting/status").get_json()["state"] == "paused"

    resume_response = logged_in_client.post("/api/admin/voting/resume")
    assert resume_response.status_code == 200
    assert resume_response.get_json()["voting_paused"] is False
    assert client.get("/api/voting/status").get_json()["state"] == "open"


def test_every_change_writes_an_audit_row_with_old_and_new_values(app, logged_in_client):
    logged_in_client.patch("/api/admin/voting-settings", json={"vote_fee_cedis": "1.50"})

    with app.app_context():
        row = AuditLog.query.filter_by(action="voting_settings.update").first()
        assert row is not None
        assert row.details["vote_fee_pesewas"]["before"] == 100
        assert row.details["vote_fee_pesewas"]["after"] == 150

    pause_response = logged_in_client.post("/api/admin/voting/pause")
    assert pause_response.status_code == 200

    with app.app_context():
        row = AuditLog.query.filter_by(action="voting_settings.pause").first()
        assert row is not None
        assert row.details["voting_paused"]["before"] is False
        assert row.details["voting_paused"]["after"] is True
