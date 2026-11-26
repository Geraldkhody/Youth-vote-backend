"""Dev-only tool: posts a fulfilment request to the local fulfilment URL
for one USSD session id, so (with HUBTEL_MODE=fake in .env) the whole
fulfilment flow -- status check, vote, final callback -- can be exercised
locally without a real Hubtel account.

Run with the backend already running on port 5001 and HUBTEL_PATH_TOKEN
set in .env, from backend/:

    python scripts/simulate_fulfilment.py <session_id>

Use scripts/ussd_simulator.py first to get a session id with a real
pending transaction behind it.
"""

import os
import sys

# Refuse to run anywhere near production -- this hits the real fulfilment
# endpoint directly, with no confirmation prompt.
if os.environ.get("APP_ENV") == "production":
    print("Refusing to run: APP_ENV=production.")
    sys.exit(1)

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://127.0.0.1:5001"
TOKEN = os.environ.get("HUBTEL_PATH_TOKEN", "")


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/simulate_fulfilment.py <session_id>")
        sys.exit(1)

    if not TOKEN:
        print("HUBTEL_PATH_TOKEN is not set in .env -- can't build the fulfilment URL.")
        sys.exit(1)

    session_id = sys.argv[1]
    url = f"{BASE_URL}/api/hubtel/{TOKEN}/fulfillment"

    # Matches the ASSUMED shape in tests/fixtures/fulfilment_request_ASSUMED.json
    # -- VERIFY once the real body is captured from Hubtel.
    body = {"SessionId": session_id, "OrderId": f"SIM-{session_id}"}

    response = requests.post(url, json=body, timeout=10)
    print(f"HTTP {response.status_code}")
    print(response.text)


if __name__ == "__main__":
    main()
