def test_merge_pending_nomination_into_nominee_same_category(
    logged_in_client, make_pending_nomination, make_active_nominee, active_category
):
    nominee = make_active_nominee(category_id=active_category)
    nomination_id = make_pending_nomination(category_id=active_category, nominee_name="Duplicate Entry")

    response = logged_in_client.post(
        f"/api/nominations/{nomination_id}/merge", json={"nominee_id": nominee["id"]}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "approved"
    assert data["nominee_id"] == nominee["id"]
    assert data["reviewed_at"] is not None


def test_merge_refuses_different_category(
    logged_in_client, make_pending_nomination, make_active_nominee, active_category, second_active_category
):
    nominee = make_active_nominee(category_id=second_active_category)
    nomination_id = make_pending_nomination(category_id=active_category)

    response = logged_in_client.post(
        f"/api/nominations/{nomination_id}/merge", json={"nominee_id": nominee["id"]}
    )

    assert response.status_code == 400
    assert "category" in response.get_json()["error"]


def test_merge_refuses_already_approved_nomination(
    logged_in_client, make_pending_nomination, make_active_nominee, active_category
):
    nominee = make_active_nominee(category_id=active_category)
    nomination_id = make_pending_nomination(category_id=active_category)
    logged_in_client.post(f"/api/nominations/{nomination_id}/approve")

    response = logged_in_client.post(
        f"/api/nominations/{nomination_id}/merge", json={"nominee_id": nominee["id"]}
    )

    assert response.status_code == 400
    assert "pending" in response.get_json()["error"]


def test_merge_refuses_inactive_nominee(
    logged_in_client, make_pending_nomination, make_active_nominee, active_category
):
    nominee = make_active_nominee(category_id=active_category)
    logged_in_client.post(f"/api/nominees/{nominee['id']}/deactivate", json={"reason": "Withdrew"})
    nomination_id = make_pending_nomination(category_id=active_category)

    response = logged_in_client.post(
        f"/api/nominations/{nomination_id}/merge", json={"nominee_id": nominee["id"]}
    )

    assert response.status_code == 400
    assert "inactive" in response.get_json()["error"]
