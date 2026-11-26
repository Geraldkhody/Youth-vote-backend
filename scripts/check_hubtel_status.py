"""Manual dev tool: makes ONE real call to Hubtel's transaction
status-check API, using the credentials in .env, and prints the raw
response.

Run from backend/, with .venv active and real Hubtel credentials set in
.env (HUBTEL_COLLECTION_ACCOUNT, HUBTEL_API_ID, HUBTEL_API_SECRET):

    python scripts/check_hubtel_status.py <client_reference>

Use this to capture the real response format -- docs/HUBTEL_USSD_NOTES.md
marks it VERIFY until we've actually seen one. Never prints the API
secret, and masks any phone number in the response body.
"""

import json
import os
import re
import sys

# Running this file directly only puts scripts/ on sys.path, not the
# backend root -- add it so `from app import ...` below can find it.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.providers.hubtel import HubtelError, check_transaction_status

# Same phone-number shape masked in app/services/hubtel.py.
PHONE_PATTERN = re.compile(r"\d{9,15}")


def _mask_phone_numbers(text):
    return PHONE_PATTERN.sub(lambda match: "*" * (len(match.group()) - 3) + match.group()[-3:], text)


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_hubtel_status.py <client_reference>")
        sys.exit(1)

    client_reference = sys.argv[1]
    app = create_app()

    with app.app_context():
        try:
            status_code, raw_json = check_transaction_status(client_reference)
        except HubtelError as error:
            print(f"Error: {error}")
            sys.exit(1)

    print(f"HTTP status: {status_code}")
    print("Raw body (phone numbers masked):")
    print(_mask_phone_numbers(json.dumps(raw_json, indent=2)))


if __name__ == "__main__":
    main()
