"""Client for Hubtel's transaction status-check API: makes the real HTTP
call. See app/providers/hubtel_adapter.py for parsing its (not yet
captured -- VERIFY) response shape -- that's re-exported below so
existing callers/imports don't need to change.
"""

import base64

import requests
from flask import current_app

from app.providers.hubtel_adapter import parse_status_response  # noqa: F401 (re-exported)

REQUEST_TIMEOUT_SECONDS = 10


class HubtelError(Exception):
    """Raised when the status-check call can't be completed, or Hubtel
    returns something other than a 200. The message is always safe to log
    or show -- it never includes HUBTEL_API_SECRET or any other
    credential."""


def _require_config():
    collection_account = current_app.config.get("HUBTEL_COLLECTION_ACCOUNT")
    api_id = current_app.config.get("HUBTEL_API_ID")
    api_secret = current_app.config.get("HUBTEL_API_SECRET")
    base_url = current_app.config.get("HUBTEL_STATUS_BASE_URL")

    if not all([collection_account, api_id, api_secret, base_url]):
        raise HubtelError(
            "Hubtel status-check configuration is incomplete -- set "
            "HUBTEL_COLLECTION_ACCOUNT, HUBTEL_API_ID, HUBTEL_API_SECRET "
            "and HUBTEL_STATUS_BASE_URL."
        )

    return collection_account, api_id, api_secret, base_url


def _basic_auth_header(api_id, api_secret):
    token = base64.b64encode(f"{api_id}:{api_secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def check_transaction_status(client_reference):
    """GET Hubtel's transaction status-check endpoint for one reference.

    Our reading is that `client_reference` is the USSD SessionId --
    VERIFY (see docs/HUBTEL_USSD_NOTES.md).

    Returns (http_status_code, raw_json) on a 200 response. Raises
    HubtelError -- with a safe, secret-free message -- on a network
    error, a timeout, or any non-200 response. One attempt only, no
    hidden retries: a caller that wants to retry should do so explicitly.
    """
    collection_account, api_id, api_secret, base_url = _require_config()
    url = f"{base_url}/transactions/{collection_account}/status"

    try:
        response = requests.get(
            url,
            params={"clientReference": client_reference},
            headers={"Authorization": _basic_auth_header(api_id, api_secret)},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise HubtelError(f"could not reach Hubtel's status-check API: {type(error).__name__}") from error

    if response.status_code != 200:
        raise HubtelError(f"Hubtel's status-check API returned HTTP {response.status_code}")

    return response.status_code, response.json()
