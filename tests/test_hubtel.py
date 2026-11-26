from app.extensions import db
from app.models.hubtel_log import HubtelLog
from app import create_app

HUBTEL_TOKEN = "test-hubtel-token-with-24-plus-chars"


def _app_with_hubtel(overrides=None):
    """A test app with a valid HUBTEL_PATH_TOKEN configured, so the Hubtel
    routes register. The shared `app` fixture doesn't set this, since most
    tests don't care about Hubtel at all."""
    config = {
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "TESTING": True,
        "HUBTEL_PATH_TOKEN": HUBTEL_TOKEN,
    }
    if overrides:
        config.update(overrides)
    return create_app(config)


def test_interaction_with_right_token_returns_expected_shape():
    """With no voting window configured, the menu (app/services/ussd.py)
    ends the session with a "not scheduled" message -- the full menu walk
    is covered in tests/test_ussd.py; this just proves the route wires it
    up and returns Hubtel's required JSON shape."""
    app = _app_with_hubtel()
    with app.app_context():
        db.create_all()
        client = app.test_client()

        response = client.post(
            f"/api/hubtel/{HUBTEL_TOKEN}/interaction",
            json={
                "Type": "initiation",
                "Message": "*920*123#",
                "ServiceCode": "920",
                "Operator": "mtn",
                "Mobile": "233200585542",
                "SessionId": "abc123",
                "Sequence": 1,
                "Platform": "USSD",
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["SessionId"] == "abc123"
        assert body["Type"] == "release"
        assert "not" in body["Message"].lower()  # "not scheduled yet"
        assert body["Label"]
        assert body["DataType"] == "display"
        assert body["FieldType"] == "text"

        db.drop_all()


def test_interaction_with_wrong_token_returns_404():
    app = _app_with_hubtel()
    with app.app_context():
        db.create_all()
        client = app.test_client()

        response = client.post(
            "/api/hubtel/wrong-token/interaction",
            json={"SessionId": "abc123"},
        )

        assert response.status_code == 404
        db.drop_all()


def test_fulfillment_with_unknown_session_returns_200_and_changes_nothing_but_log():
    """"abc123" doesn't match any real transaction's hubtel_session_id --
    handle_fulfilment_request (app/services/hubtel_fulfilment.py) treats
    that as "unknown_session" and changes nothing. The route still always
    replies 200 regardless."""
    app = _app_with_hubtel()
    with app.app_context():
        db.create_all()
        client = app.test_client()

        response = client.post(
            f"/api/hubtel/{HUBTEL_TOKEN}/fulfillment",
            json={"SessionId": "abc123", "OrderId": "ORD1", "Mobile": "233200585542"},
        )

        assert response.status_code == 200
        assert response.get_json()["status"] == "received"

        # Only the HubtelLog row was written -- nothing else changed.
        logs = HubtelLog.query.filter_by(kind="fulfillment").all()
        assert len(logs) == 1

        db.drop_all()


def test_fulfillment_with_unparseable_body_returns_200_and_changes_nothing_but_log():
    """A body with no "SessionId" at all can't even be matched to a
    transaction -- handle_fulfilment_request treats that as "unparsed"
    and changes nothing, but the route still replies 200."""
    app = _app_with_hubtel()
    with app.app_context():
        db.create_all()
        client = app.test_client()

        response = client.post(
            f"/api/hubtel/{HUBTEL_TOKEN}/fulfillment",
            json={"SomeUnexpectedField": "whatever"},
        )

        assert response.status_code == 200
        assert response.get_json()["status"] == "received"

        logs = HubtelLog.query.filter_by(kind="fulfillment").all()
        assert len(logs) == 1

        db.drop_all()


def test_phone_numbers_are_masked_in_stored_log():
    app = _app_with_hubtel()
    with app.app_context():
        db.create_all()
        client = app.test_client()

        client.post(
            f"/api/hubtel/{HUBTEL_TOKEN}/interaction",
            json={
                "Type": "initiation",
                "ServiceCode": "920",
                "Mobile": "233200585542",
                "SessionId": "abc123",
                "Sequence": 1,
            },
        )

        log = HubtelLog.query.filter_by(kind="interaction").first()
        assert log is not None
        assert log.body["Mobile"] == "*********542"
        assert "200585542" not in str(log.body)

        db.drop_all()


def test_oversized_body_is_truncated_and_flagged():
    app = _app_with_hubtel()
    with app.app_context():
        db.create_all()
        client = app.test_client()

        huge_message = "x" * 30_000
        client.post(
            f"/api/hubtel/{HUBTEL_TOKEN}/interaction",
            json={
                "Type": "response",
                "Message": huge_message,
                "SessionId": "abc123",
            },
        )

        log = HubtelLog.query.filter_by(kind="interaction").first()
        assert log is not None
        assert log.body["_truncated"] is True
        assert log.body["_original_length"] > 20 * 1024
        assert len(log.body["body"]) <= 20 * 1024

        db.drop_all()


def test_hubtel_routes_do_not_register_when_token_missing():
    app = _app_with_hubtel(overrides={"HUBTEL_PATH_TOKEN": ""})
    with app.app_context():
        db.create_all()
        client = app.test_client()

        response = client.post(f"/api/hubtel/{HUBTEL_TOKEN}/interaction", json={})

        # No blueprint registered at all -- Flask's own 404, not ours.
        assert response.status_code == 404

        db.drop_all()


def test_hubtel_routes_do_not_register_when_token_too_short():
    app = _app_with_hubtel(overrides={"HUBTEL_PATH_TOKEN": "short-token"})
    with app.app_context():
        db.create_all()
        client = app.test_client()

        response = client.post("/api/hubtel/short-token/interaction", json={})

        assert response.status_code == 404
        db.drop_all()


def test_admin_hubtel_log_returns_401_when_logged_out():
    app = _app_with_hubtel()
    with app.app_context():
        db.create_all()
        client = app.test_client()

        response = client.get("/api/admin/hubtel-log")

        assert response.status_code == 401
        db.drop_all()
