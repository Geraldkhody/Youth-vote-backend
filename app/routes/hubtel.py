import hmac

from flask import Blueprint, current_app, jsonify, request

from app.services.hubtel import get_client_ip, store_hubtel_log
from app.services.hubtel_fulfilment import handle_fulfilment_request
from app.services.ussd import handle_interaction

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
    response_body = handle_interaction(body)

    store_hubtel_log(kind="interaction", raw_body=body, response_status=200, source_ip=get_client_ip(request))
    return jsonify(response_body), 200


@hubtel_bp.post("/<token>/fulfillment")
def fulfillment(token):
    if not _token_is_valid(token):
        return "", 404

    client_ip = get_client_ip(request)
    allowed_ips = current_app.config.get("HUBTEL_FULFILMENT_ALLOWED_IPS") or []
    if allowed_ips and client_ip not in allowed_ips:
        # Looks exactly like a route that doesn't exist -- same reasoning
        # as the wrong-token case above, and the log still records it
        # (as "blocked") so a wrongly-tightened allowlist is visible,
        # not just silently dropped. See config.py's comment on
        # HUBTEL_FULFILMENT_ALLOWED_IPS before ever turning this on.
        body = request.get_json(silent=True) or {}
        store_hubtel_log(kind="blocked", raw_body=body, response_status=404, source_ip=client_ip)
        return "", 404

    body = request.get_json(silent=True) or {}

    # handle_fulfilment_request never raises (see its docstring) -- if it
    # ever did, we'd still want to log the request first.
    store_hubtel_log(kind="fulfillment", raw_body=body, response_status=200, source_ip=client_ip)
    handle_fulfilment_request(body)

    # Always 200, always this same tiny body, regardless of what
    # happened internally (unparsed body, unknown session, wrong amount,
    # etc.) -- never expose internal details in the reply. What Hubtel
    # actually expects back here is still an open item (not captured in
    # their docs yet).
    return jsonify(status="received"), 200
