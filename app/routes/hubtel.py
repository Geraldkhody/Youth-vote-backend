import hmac

from flask import Blueprint, current_app, jsonify, request

from app.services.hubtel import store_hubtel_log

# This is a STUB: it proves the hosting and request shapes work, with no
# voting, payment or menu logic. See docs/HUBTEL_USSD_NOTES.md.
hubtel_bp = Blueprint("hubtel", __name__, url_prefix="/api/hubtel")


def _token_is_valid(token):
    expected = current_app.config["HUBTEL_PATH_TOKEN"]
    # hmac.compare_digest instead of == so a wrong token can't be guessed
    # one character at a time via response-time differences.
    return hmac.compare_digest(token, expected)


@hubtel_bp.post("/<token>/interaction")
def interaction(token):
    if not _token_is_valid(token):
        # No detail in the body -- a wrong token should look exactly like a
        # route that doesn't exist, not reveal that the path is "close".
        return "", 404

    body = request.get_json(silent=True) or {}
    session_id = body.get("SessionId", "")
    event_name = body.get("ServiceCode", "Youth Awards")

    # Required response shape per docs/HUBTEL_USSD_NOTES.md: a short
    # message that immediately ends the session (Type "release").
    response_body = {
        "SessionId": session_id,
        "Type": "release",
        "Message": f"{event_name}: voting opens soon",
        "Label": "Youth Awards Voting",
        "DataType": "display",
        "FieldType": "text",
    }

    store_hubtel_log(kind="interaction", raw_body=body, response_status=200)
    return jsonify(response_body), 200


@hubtel_bp.post("/<token>/fulfillment")
def fulfillment(token):
    if not _token_is_valid(token):
        return "", 404

    body = request.get_json(silent=True) or {}

    # Stub only: record the request and acknowledge it. Does not create a
    # vote, record a payment, or change anything else.
    store_hubtel_log(kind="fulfillment", raw_body=body, response_status=200)
    return jsonify(status="received"), 200
