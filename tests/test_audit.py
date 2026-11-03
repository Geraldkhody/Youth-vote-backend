import json

from app.extensions import db
from app.models.admin_user import AdminUser
from app.models.audit_log import AuditLog


def test_approve_writes_one_audit_row(app, logged_in_client, make_pending_nomination):
    nomination_id = make_pending_nomination()

    logged_in_client.post(f"/api/nominations/{nomination_id}/approve")

    with app.app_context():
        rows = AuditLog.query.filter_by(action="nomination.approve").all()
        assert len(rows) == 1
        assert rows[0].entity_id == nomination_id


def test_failed_approval_leaves_no_audit_row(app, logged_in_client, make_pending_nomination):
    nomination_id = make_pending_nomination()
    logged_in_client.post(f"/api/nominations/{nomination_id}/reject", json={"reason": "Incomplete"})

    # Approving an already-rejected nomination fails validation before any
    # audit row (or anything else) is written.
    response = logged_in_client.post(f"/api/nominations/{nomination_id}/approve")
    assert response.status_code == 400

    with app.app_context():
        rows = AuditLog.query.filter_by(action="nomination.approve", entity_id=nomination_id).all()
        assert rows == []


def test_patch_writes_audit_row_with_old_and_new_phone(app, logged_in_client, make_active_nominee):
    nominee = make_active_nominee()

    logged_in_client.patch(f"/api/nominees/{nominee['id']}", json={"phone": "0509999999"})

    with app.app_context():
        row = AuditLog.query.filter_by(action="nominee.edit", entity_id=nominee["id"]).first()
        assert row is not None
        assert row.details["phone"]["before"] == "233241234567"
        assert row.details["phone"]["after"] == "233509999999"


def test_merge_writes_audit_row(app, logged_in_client, make_pending_nomination, make_active_nominee, active_category):
    nominee = make_active_nominee(category_id=active_category)
    nomination_id = make_pending_nomination(category_id=active_category)

    logged_in_client.post(f"/api/nominations/{nomination_id}/merge", json={"nominee_id": nominee["id"]})

    with app.app_context():
        row = AuditLog.query.filter_by(action="nomination.merge", entity_id=nomination_id).first()
        assert row is not None
        assert row.details["nominee_id"] == nominee["id"]


def test_audit_log_endpoint_requires_login(client):
    response = client.get("/api/audit-log")

    assert response.status_code == 401


def test_audit_log_endpoint_works_when_logged_in(logged_in_client, make_pending_nomination):
    nomination_id = make_pending_nomination()
    logged_in_client.post(f"/api/nominations/{nomination_id}/approve")

    response = logged_in_client.get("/api/audit-log")

    assert response.status_code == 200
    actions = [row["action"] for row in response.get_json()]
    assert "admin.login" in actions
    assert "nomination.approve" in actions


def test_no_password_or_hash_in_any_audit_row(app, logged_in_client, make_pending_nomination, make_active_nominee, admin_user):
    # Exercise every action that writes an audit row.
    nomination_id = make_pending_nomination()
    logged_in_client.post(f"/api/nominations/{nomination_id}/approve")
    nominee = make_active_nominee()
    logged_in_client.patch(f"/api/nominees/{nominee['id']}", json={"full_name": "Someone Else"})
    logged_in_client.post(f"/api/nominees/{nominee['id']}/deactivate", json={"reason": "Withdrew"})
    logged_in_client.post("/api/auth/logout")

    with app.app_context():
        admin = AdminUser.query.get(admin_user)
        password_hash = admin.password_hash

        for row in AuditLog.query.all():
            serialized = json.dumps(row.details or {})
            assert "password" not in serialized.lower()
            assert "secret123" not in serialized
            assert password_hash not in serialized
