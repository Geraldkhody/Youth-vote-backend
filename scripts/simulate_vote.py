"""Development helper: exercises the transaction/vote services directly
against the dev database (no HTTP, no Hubtel -- those don't exist yet).

Run with the backend's .venv active, from backend/:

    python scripts/simulate_vote.py

Walks through: a normal successful vote, confirming that same payment a
second time (a harmless duplicate), and a payment with the wrong amount
(refused, flagged for review). Prints real values at each step.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

# Refuse to run anywhere near production -- this script pokes at real
# transaction/vote rows directly, with no HTTP layer or confirmation
# prompts in the way.
if os.environ.get("APP_ENV") == "production":
    print("Refusing to run: APP_ENV=production.")
    sys.exit(1)

# Running this file directly (not as a module) only puts scripts/ on
# sys.path, not the backend root -- add it so `from app import ...` below
# can find the app package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.nominee import Nominee
from app.models.vote import Vote
from app.models.voting_settings import get_settings
from app.services.transactions import (
    create_pending_transaction,
    get_nominee_vote_total,
    record_successful_payment,
)

app = create_app()


def main():
    with app.app_context():
        nominee = Nominee.query.filter_by(is_active=True).first()
        if nominee is None:
            print("No active nominee found in the dev database. Approve a nomination first.")
            return

        print(f"Using nominee: {nominee.full_name!r} (id={nominee.id}, code={nominee.code})\n")

        # This script only cares about the transaction/vote logic, not
        # about scheduling -- so make sure voting is open for the
        # duration of the run, and put the previous setting back after.
        settings = get_settings()
        previous_opens_at = settings.voting_opens_at
        previous_closes_at = settings.voting_closes_at
        previous_paused = settings.voting_paused

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        settings.voting_opens_at = now - timedelta(days=1)
        settings.voting_closes_at = now + timedelta(days=1)
        settings.voting_paused = False
        db.session.commit()
        print(f"(temporarily opened voting {settings.voting_opens_at} -> {settings.voting_closes_at} for this run)\n")

        try:
            print("--- Step 1: create a pending transaction ---")
            transaction = create_pending_transaction(
                nominee_id=nominee.id,
                phone="233200111222",
                quantity=3,
                channel="web",
            )
            print(f"created: reference={transaction.reference}, status={transaction.status}, "
                  f"quantity={transaction.quantity}, unit_fee_pesewas={transaction.unit_fee_pesewas}, "
                  f"amount_pesewas={transaction.amount_pesewas}\n")

            print("--- Step 2: record a successful payment for it ---")
            transaction = record_successful_payment(
                transaction.reference, paid_amount_pesewas=transaction.amount_pesewas,
                provider_total_pesewas=transaction.amount_pesewas + 5,
            )
            vote = Vote.query.filter_by(transaction_id=transaction.id).first()
            print(f"status={transaction.status}, confirmed_at={transaction.confirmed_at}, "
                  f"needs_review={transaction.needs_review}")
            print(f"vote created: id={vote.id if vote else None}, "
                  f"quantity={vote.quantity if vote else None}\n")

            print("--- Step 3: record the SAME successful payment again (duplicate) ---")
            votes_before = Vote.query.filter_by(transaction_id=transaction.id).count()
            transaction = record_successful_payment(
                transaction.reference, paid_amount_pesewas=transaction.amount_pesewas,
            )
            votes_after = Vote.query.filter_by(transaction_id=transaction.id).count()
            print(f"status={transaction.status} (unchanged), "
                  f"votes for this transaction before={votes_before}, after={votes_after} (should be equal)\n")

            print("--- Step 4: a second transaction, confirmed with the WRONG amount ---")
            transaction_2 = create_pending_transaction(
                nominee_id=nominee.id,
                phone="233200111222",
                quantity=2,
                channel="web",
            )
            wrong_amount = transaction_2.amount_pesewas + 1
            transaction_2 = record_successful_payment(
                transaction_2.reference, paid_amount_pesewas=wrong_amount,
            )
            vote_2 = Vote.query.filter_by(transaction_id=transaction_2.id).first()
            print(f"expected amount_pesewas={transaction_2.amount_pesewas}, paid={wrong_amount}")
            print(f"status={transaction_2.status} (should stay 'pending'), "
                  f"needs_review={transaction_2.needs_review}, review_reason={transaction_2.review_reason!r}")
            print(f"vote created: {vote_2} (should be None)\n")

            print("--- Totals ---")
            print(f"nominee {nominee.code} total votes: {get_nominee_vote_total(nominee.id)}")

        finally:
            settings.voting_opens_at = previous_opens_at
            settings.voting_closes_at = previous_closes_at
            settings.voting_paused = previous_paused
            db.session.commit()
            print(f"\n(restored voting settings to opens_at={previous_opens_at}, "
                  f"closes_at={previous_closes_at}, paused={previous_paused})")


if __name__ == "__main__":
    main()
