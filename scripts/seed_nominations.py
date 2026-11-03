"""Development helper: creates sample nominations through the public API.

Not used in production. Run with the backend already running on port 5001:

    python scripts/seed_nominations.py

Everything goes through HTTP, the same way the frontend will -- no direct
database access.
"""

import requests

BASE_URL = "http://127.0.0.1:5001"

# Five sample nominees, each using a different accepted phone format
# (0XXXXXXXXX, 233XXXXXXXXX, +233XXXXXXXXX) so we cover all three.
SAMPLE_NOMINATIONS = [
    {
        "nominee_name": "Kwame Asante",
        "nominee_phone": "0244123456",
        "nominator_name": "Ama Boateng",
        "nominator_phone": "0201234567",
    },
    {
        "nominee_name": "Akosua Mensah",
        "nominee_phone": "233244111222",
        "nominator_name": "Yaw Owusu",
        "nominator_phone": "233201234567",
    },
    {
        "nominee_name": "Kofi Adjei",
        "nominee_phone": "+233244333444",
        "nominator_name": "Abena Darko",
        "nominator_phone": "+233201234567",
    },
    {
        "nominee_name": "Efua Addo",
        "nominee_phone": "0244555666",
        "nominator_name": "Kojo Appiah",
        "nominator_phone": "0201234567",
    },
    {
        "nominee_name": "Yaa Agyeman",
        "nominee_phone": "233244777888",
        "nominator_name": "Kwabena Osei",
        "nominator_phone": "233201234567",
    },
]

# Deliberately invalid: phone "123" should be rejected by the API's validation.
INVALID_NOMINATION = {
    "nominee_name": "Bad Phone Test",
    "nominee_phone": "123",
    "nominator_name": "Test Nominator",
    "nominator_phone": "0201234567",
}


def get_first_active_category():
    response = requests.get(f"{BASE_URL}/api/categories")
    response.raise_for_status()
    categories = response.json()

    for category in categories:
        if category["is_active"]:
            return category

    return None


def post_nomination(category_id, nomination_number, fields):
    payload = {"category_id": category_id, **fields}
    response = requests.post(f"{BASE_URL}/api/nominations", json=payload)

    if response.ok:
        nomination_id = response.json()["id"]
        print(f"#{nomination_number}: status {response.status_code}, saved as nomination id {nomination_id}")
    else:
        error = response.json().get("error", "unknown error")
        print(f"#{nomination_number}: status {response.status_code}, error: {error}")


def main():
    category = get_first_active_category()
    if category is None:
        print("No active categories found. Create one before running this script.")
        return

    print(f"Using category: {category['name']} (id {category['id']})\n")

    for number, fields in enumerate(SAMPLE_NOMINATIONS, start=1):
        post_nomination(category["id"], number, fields)

    # One more request with a bad phone number, to confirm validation works.
    post_nomination(category["id"], len(SAMPLE_NOMINATIONS) + 1, INVALID_NOMINATION)


if __name__ == "__main__":
    main()
