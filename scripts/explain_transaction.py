"""Manual dev/ops tool: explains exactly why one transaction is (or
isn't) confirmed paid, by running the SAME decision path the sweep uses
for it -- the real status-check call, the same parsing, the same
rules -- and printing every step.

Dry-run by default: makes the real (read-only) call to Hubtel's
status-check API so the explanation is accurate, but makes NO database
write at all. Pass --apply to actually process the transaction for real
(exactly what `flask hubtel-sweep` or the fulfilment endpoint would do).

Refuses to run at all with HUBTEL_MODE=fake -- that mode never calls the
real Hubtel API, so there would be nothing real to explain.

Run from backend/, with .venv active:

    python scripts/explain_transaction.py <reference>
    python scripts/explain_transaction.py <reference> --apply
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models.transaction import Transaction
from app.providers.hubtel import HubtelError
from app.providers.hubtel_adapter import find_order_id_in_status_response
from app.services.hubtel import mask_phone_numbers
from app.services.hubtel_fulfilment import (
    check_hubtel_status_for_transaction,
    evaluate_hubtel_error,
    evaluate_payment_check,
    process_hubtel_payment,
)


def _mask_phone(phone):
    if not phone or len(phone) <= 3:
        return phone
    return "*" * (len(phone) - 3) + phone[-3:]


def _print_transaction_fields(transaction):
    print("Transaction:")
    print(f"  reference:               {transaction.reference}")
    print(f"  id:                      {transaction.id}")
    print(f"  status:                  {transaction.status}")
    print(f"  needs_review:            {transaction.needs_review}")
    print(f"  review_reason:           {transaction.review_reason}")
    print(f"  phone:                   {_mask_phone(transaction.phone)}")
    print(f"  quantity:                {transaction.quantity}")
    print(f"  amount_pesewas:          {transaction.amount_pesewas} (the vote amount -- what must match)")
    print(f"  hubtel_session_id:       {transaction.hubtel_session_id}")
    print(f"  hubtel_order_id:         {transaction.hubtel_order_id}")
    print(f"  fulfilment_received_at:  {transaction.fulfilment_received_at}")
    print(f"  last_status_check_at:    {transaction.last_status_check_at}")
    print(f"  last_status_outcome:     {transaction.last_status_outcome}")
    print(f"  last_status_note:        {transaction.last_status_note}")


def _print_what_record_successful_payment_would_do(transaction, status, amount_pesewas, blocking_rules):
    print("\nWhat record_successful_payment WOULD do:")
    if transaction.status == "success":
        print("  Nothing -- this transaction is already 'success' (idempotent no-op).")
        return
    if transaction.status in ("failed", "cancelled"):
        print(f"  Flag needs_review -- a confirmation arrived for a transaction already '{transaction.status}'.")
        return
    if status != "paid":
        print(f"  Nothing -- the status check did not report 'paid' (got '{status}').")
        return
    if any("order id mismatch" in rule for rule in blocking_rules):
        print("  Nothing -- blocked before reaching record_successful_payment (order id mismatch).")
        return
    if amount_pesewas is None:
        print("  Nothing -- blocked before reaching record_successful_payment (amount unreadable).")
        return
    if amount_pesewas != transaction.amount_pesewas:
        print(
            f"  Flag needs_review -- paid amount {amount_pesewas} does not match "
            f"the expected amount {transaction.amount_pesewas}. No vote would be created."
        )
        return
    print(f"  Create exactly one Vote of quantity {transaction.quantity}, mark 'success', send the final callback.")


def run(app, reference, apply_changes=False):
    """Does the actual work, against an already-built app -- separated
    from main() so tests can call this directly with a test app instead
    of going through create_app() (real .env config, real database).

    Returns True if it ran to completion, False if it refused/couldn't
    find the transaction (matches main()'s exit-code-1 cases).
    """
    with app.app_context():
        if app.config.get("HUBTEL_MODE") == "fake":
            print("Refusing to run: HUBTEL_MODE=fake never calls the real Hubtel API.")
            return False

        transaction = Transaction.query.filter_by(reference=reference).first()
        if transaction is None:
            print(f"No transaction found with reference {reference!r}.")
            return False

        _print_transaction_fields(transaction)

        reference_for_hubtel = transaction.hubtel_session_id or transaction.reference
        print(f"\nclient_reference used for the status check: {reference_for_hubtel}")

        status, amount_pesewas, provider_total_pesewas, raw_json, error = check_hubtel_status_for_transaction(transaction)

        if error is not None:
            print(f"\nHTTP status-check call failed: {error} (kind={error.kind}, status_code={error.status_code})")
            result = evaluate_hubtel_error(error)
            blocking_rules = result["blocking_rules"]
        else:
            print("\nHTTP status: 200")
            print("Raw body (phone numbers masked):")
            print(json.dumps(mask_phone_numbers(raw_json), indent=2))

            order_id_in_response = find_order_id_in_status_response(raw_json)
            print("\nparse_status_response:")
            print(f"  status:                 {status}")
            print(f"  amount_pesewas:         {amount_pesewas}")
            print(f"  provider_total_pesewas: {provider_total_pesewas}")
            print(f"  order id in response:   {order_id_in_response}")

            result = evaluate_payment_check(transaction, status, amount_pesewas, provider_total_pesewas, raw_json)
            blocking_rules = result["blocking_rules"]

        print(f"\nResulting last_status_outcome: {result['outcome']}")
        print(f"Resulting last_status_note:    {result['note']}")

        if blocking_rules:
            print("\nRules that blocked a 'paid' outcome:")
            for rule in blocking_rules:
                print(f"  - {rule}")
        else:
            print("\nRules that blocked a 'paid' outcome: none")

        _print_what_record_successful_payment_would_do(transaction, status, amount_pesewas, blocking_rules)

        if not apply_changes:
            print("\nDry run only -- no database write was made. Pass --apply to process this transaction for real.")
            return True

        print("\n--apply given: processing this transaction for real now...")
        process_hubtel_payment(transaction.id)

        transaction = Transaction.query.filter_by(reference=reference).first()
        print("\nAfter processing:")
        _print_transaction_fields(transaction)
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", help="Transaction.reference, e.g. VAB12CD34EF56")
    parser.add_argument("--apply", action="store_true", help="Actually process the transaction (real writes).")
    args = parser.parse_args()

    ok = run(create_app(), args.reference, apply_changes=args.apply)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
