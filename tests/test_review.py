import re


def test_approve_creates_nominee_with_valid_code(logged_in_client, make_pending_nomination):
    nomination_id = make_pending_nomination()

    response = logged_in_client.post(f"/api/nominations/{nomination_id}/approve")

    assert response.status_code == 201
    nominee = response.get_json()
    assert re.fullmatch(r"A[1-9][0-9]", nominee["code"])  # letter + two digits
    number = int(nominee["code"][1:])
    assert 10 <= number <= 99
    assert nominee["full_name"] == "Ama Owusu"


def test_codes_within_category_never_repeat(logged_in_client, make_pending_nomination):
    # Approve enough nominations that random collisions are very likely,
    # to prove the generator actually avoids repeats rather than just
    # getting lucky.
    codes = []
    for _ in range(30):
        nomination_id = make_pending_nomination()
        response = logged_in_client.post(f"/api/nominations/{nomination_id}/approve")
        codes.append(response.get_json()["code"])

    assert len(codes) == len(set(codes))


def test_approving_rejected_nomination_is_refused(logged_in_client, make_pending_nomination):
    nomination_id = make_pending_nomination()
    logged_in_client.post(f"/api/nominations/{nomination_id}/reject", json={"reason": "Incomplete details"})

    response = logged_in_client.post(f"/api/nominations/{nomination_id}/approve")

    assert response.status_code == 400
    assert "pending" in response.get_json()["error"]


def test_rejecting_requires_reason(logged_in_client, make_pending_nomination):
    nomination_id = make_pending_nomination()

    response = logged_in_client.post(f"/api/nominations/{nomination_id}/reject", json={})

    assert response.status_code == 400
    assert "reason" in response.get_json()["error"]


def test_status_filter_works(logged_in_client, make_pending_nomination):
    pending_id = make_pending_nomination()
    approved_id = make_pending_nomination()
    logged_in_client.post(f"/api/nominations/{approved_id}/approve")

    response = logged_in_client.get("/api/nominations?status=pending")

    assert response.status_code == 200
    ids = [n["id"] for n in response.get_json()]
    assert pending_id in ids
    assert approved_id not in ids


def test_review_endpoints_require_login(client, make_pending_nomination):
    nomination_id = make_pending_nomination()

    assert client.get("/api/nominations").status_code == 401
    assert client.post(f"/api/nominations/{nomination_id}/approve").status_code == 401
    assert client.post(f"/api/nominations/{nomination_id}/reject", json={"reason": "x"}).status_code == 401
