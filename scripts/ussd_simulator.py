"""Interactive dev tool: walk the USSD menu locally, the way a real
Hubtel USSD session would, without needing a phone or a Hubtel account.

Run with the backend already running on port 5001 (flask run --port 5001)
and HUBTEL_PATH_TOKEN set in .env, from backend/:

    python scripts/ussd_simulator.py

Sends Hubtel-shaped requests to the local interaction URL, prints each
response, and lets you type the next reply.
"""

import os
import sys
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://127.0.0.1:5001"
TOKEN = os.environ.get("HUBTEL_PATH_TOKEN", "")

# A fake but validly-shaped phone, same as used elsewhere in this
# project's dev scripts.
SIMULATED_MOBILE = "233200585542"


def _send(session_id, message, sequence, request_type):
    url = f"{BASE_URL}/api/hubtel/{TOKEN}/interaction"
    body = {
        "Type": request_type,
        "Message": message,
        "ServiceCode": "920",
        "Operator": "mtn",
        "ClientState": "",
        "Mobile": SIMULATED_MOBILE,
        "SessionId": session_id,
        "Sequence": sequence,
        "Platform": "USSD",
    }
    return requests.post(url, json=body, timeout=10)


def main():
    if not TOKEN:
        print("HUBTEL_PATH_TOKEN is not set in .env -- can't build the interaction URL.")
        sys.exit(1)

    session_id = f"sim-{uuid.uuid4().hex[:12]}"
    print(f"Session: {session_id}\n")

    sequence = 1
    response = _send(session_id, "*920#", sequence, "initiation")

    while True:
        print(f"--- response #{sequence} ---")
        print(response.text)

        if response.status_code != 200:
            print("\nNon-200 response -- stopping.")
            break

        body = response.json()

        if body.get("Type") in ("release", "AddToCart"):
            print("\nSession ended.")
            break

        reply = input("\nYour reply: ").strip()
        sequence += 1
        response = _send(session_id, reply, sequence, "response")


if __name__ == "__main__":
    main()
