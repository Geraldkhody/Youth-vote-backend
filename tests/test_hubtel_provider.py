"""Tests for app/providers/hubtel.py -- the transaction status-check
client. Every test here mocks requests.get, so NONE of them makes a real
network call."""

import base64
from unittest.mock import MagicMock, patch

import pytest
import requests

from app import create_app
from app.providers.hubtel import HubtelError, check_transaction_status

HUBTEL_CONFIG = {
    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    "TESTING": True,
    "HUBTEL_COLLECTION_ACCOUNT": "ACC123",
    "HUBTEL_API_ID": "my-api-id",
    "HUBTEL_API_SECRET": "super-secret-value",
    "HUBTEL_STATUS_BASE_URL": "https://api-txnstatus.hubtel.com",
}


def _app_with_hubtel_status_config():
    return create_app(dict(HUBTEL_CONFIG))


def test_builds_the_right_url_and_basic_auth_header():
    app = _app_with_hubtel_status_config()
    with app.app_context():
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"Status": "Paid"}

        with patch("app.providers.hubtel.requests.get", return_value=mock_response) as mock_get:
            check_transaction_status("ref-123")

        called_url = mock_get.call_args.args[0]
        called_kwargs = mock_get.call_args.kwargs

        assert called_url == "https://api-txnstatus.hubtel.com/transactions/ACC123/status"
        assert called_kwargs["params"] == {"clientReference": "ref-123"}
        assert called_kwargs["timeout"] == 10

        expected_token = base64.b64encode(b"my-api-id:super-secret-value").decode("ascii")
        assert called_kwargs["headers"]["Authorization"] == f"Basic {expected_token}"


def test_returns_status_code_and_raw_json_on_success():
    app = _app_with_hubtel_status_config()
    with app.app_context():
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"Status": "Paid", "Amount": 1.5}

        with patch("app.providers.hubtel.requests.get", return_value=mock_response):
            status_code, raw_json = check_transaction_status("ref-123")

        assert status_code == 200
        assert raw_json == {"Status": "Paid", "Amount": 1.5}


def test_non_200_response_raises_hubtel_error():
    app = _app_with_hubtel_status_config()
    with app.app_context():
        mock_response = MagicMock(status_code=500)
        with patch("app.providers.hubtel.requests.get", return_value=mock_response):
            with pytest.raises(HubtelError):
                check_transaction_status("ref-123")


def test_timeout_raises_hubtel_error():
    app = _app_with_hubtel_status_config()
    with app.app_context():
        with patch("app.providers.hubtel.requests.get", side_effect=requests.Timeout()):
            with pytest.raises(HubtelError):
                check_transaction_status("ref-123")


def test_connection_error_raises_hubtel_error():
    app = _app_with_hubtel_status_config()
    with app.app_context():
        with patch("app.providers.hubtel.requests.get", side_effect=requests.ConnectionError()):
            with pytest.raises(HubtelError):
                check_transaction_status("ref-123")


def test_missing_config_raises_before_calling_hubtel():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        with patch("app.providers.hubtel.requests.get") as mock_get:
            with pytest.raises(HubtelError):
                check_transaction_status("ref-123")
            assert not mock_get.called


def test_secrets_never_appear_in_error_messages():
    app = _app_with_hubtel_status_config()
    with app.app_context():
        mock_response = MagicMock(status_code=500)
        with patch("app.providers.hubtel.requests.get", return_value=mock_response):
            with pytest.raises(HubtelError) as exc_info:
                check_transaction_status("ref-123")

        assert "super-secret-value" not in str(exc_info.value)
        assert "my-api-id" not in str(exc_info.value)


def test_secrets_never_appear_in_missing_config_error():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        with pytest.raises(HubtelError) as exc_info:
            check_transaction_status("ref-123")

        assert "super-secret-value" not in str(exc_info.value)
