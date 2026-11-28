from datetime import datetime, timedelta, timezone

import click

from app.extensions import db
from app.models.admin_user import AdminUser
from app.models.transaction import Transaction
from app.services.hubtel_fulfilment import (
    CALLBACK_FAST_RETRY_MINUTES,
    MAX_CALLBACK_ATTEMPTS,
    process_hubtel_payment,
    send_final_callback,
)

# Total items this command will touch in one run, across all checks
# combined -- a cron job calling this every minute should never need to
# chew through more than this in one go.
SWEEP_ITEM_LIMIT = 50

# Status-check retry schedule (step 1) for a pending transaction whose
# fulfilment we've received: every sweep run for the first 30 minutes
# after fulfilment, then every 5 minutes, until it's given up on (step 2,
# STATUS_CHECK_GIVE_UP_HOURS). Hubtel's one-hour final-callback deadline
# means we can't afford to wait out the normal 5-minutes-old rule once we
# know fulfilment has actually happened.
STATUS_CHECK_FAST_RETRY_MINUTES = 30
STATUS_CHECK_RETRY_COOLDOWN_MINUTES = 5
STATUS_CHECK_GIVE_UP_HOURS = 24

# Final-callback retry schedule (step 3), measured from
# fulfilment_received_at: every sweep run for the first 10 minutes, then
# every 5 minutes. send_final_callback itself enforces the real one-hour
# deadline (HUBTEL_CALLBACK_DEADLINE_MINUTES / CALLBACK_GIVE_UP_MINUTES)
# and flags needs_review once that runs out. CALLBACK_FAST_RETRY_MINUTES
# is imported from hubtel_fulfilment so the two stay in step.
CALLBACK_RETRY_COOLDOWN_MINUTES = 5


def register_cli(app):
    """Register custom `flask` CLI commands on the app."""

    @app.cli.command("create-admin")
    def create_admin():
        """Interactively create an admin user (flask create-admin)."""
        name = click.prompt("Name")
        email = click.prompt("Email").strip()
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)

        existing = AdminUser.query.filter_by(email=email).first()
        if existing is not None:
            click.echo(f"Error: an admin with email '{email}' already exists.")
            return

        admin = AdminUser(name=name, email=email, is_active=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()

        click.echo(f"Admin '{name}' ({email}) created.")

    @app.cli.command("hubtel-sweep")
    def hubtel_sweep():
        """Catches up anything stuck waiting on Hubtel. Meant to run once
        a minute from a cron job.

        Re-checks payments that haven't been confirmed yet, gives up on
        ones that never will be, and retries final-callback deliveries
        that failed. Capped at SWEEP_ITEM_LIMIT items total per run.

        Safe if two runs overlap: this command only decides WHAT to look
        at. Each individual action is made safe to repeat by the
        function that does it -- process_hubtel_payment only acts on a
        still-'pending' transaction and record_successful_payment holds
        a row lock while deciding, and send_final_callback claims a
        transaction atomically before sending anything -- so two
        overlapping sweeps picking up the same row can't both act on it.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        budget = SWEEP_ITEM_LIMIT

        checked = 0
        timed_out = 0
        retried = 0
        outcome_counts = {"paid": 0, "unpaid": 0, "refunded": 0, "unknown": 0, "error": 0}

        def _check_and_tally(transaction):
            process_hubtel_payment(transaction.id, now=now)
            refreshed = Transaction.query.filter_by(id=transaction.id).first()
            if refreshed is not None and refreshed.last_status_outcome in outcome_counts:
                outcome_counts[refreshed.last_status_outcome] += 1

        # 1a. Pending transactions whose fulfilment we've already
        # received: retry every run for the first
        # STATUS_CHECK_FAST_RETRY_MINUTES, then only every
        # STATUS_CHECK_RETRY_COOLDOWN_MINUTES -- the normal "5 minutes
        # old, checked within the last minute" rule below (1b) doesn't
        # apply to these.
        fast_retry_cutoff = now - timedelta(minutes=STATUS_CHECK_FAST_RETRY_MINUTES)
        slow_recheck_cutoff = now - timedelta(minutes=STATUS_CHECK_RETRY_COOLDOWN_MINUTES)
        fulfilled_pending_candidates = (
            Transaction.query
            .filter(Transaction.status == "pending")
            .filter(Transaction.fulfilment_received_at.isnot(None))
            .filter(db.or_(
                Transaction.fulfilment_received_at >= fast_retry_cutoff,
                Transaction.last_status_check_at.is_(None),
                Transaction.last_status_check_at < slow_recheck_cutoff,
            ))
            .order_by(Transaction.created_at)
            .limit(budget)
            .all()
        )
        for transaction in fulfilled_pending_candidates:
            _check_and_tally(transaction)
            checked += 1
        budget -= checked

        # 1b. Pending transactions that never got a fulfilment ping at
        # all -- the original, more relaxed backstop schedule: old enough
        # to check, not checked too recently.
        if budget > 0:
            check_candidates = (
                Transaction.query
                .filter(Transaction.status == "pending")
                .filter(Transaction.hubtel_session_id.isnot(None))
                .filter(Transaction.fulfilment_received_at.is_(None))
                .filter(Transaction.created_at < now - timedelta(minutes=5))
                .filter(db.or_(
                    Transaction.last_status_check_at.is_(None),
                    Transaction.last_status_check_at < now - timedelta(minutes=1),
                ))
                .order_by(Transaction.created_at)
                .limit(budget)
                .all()
            )
            for transaction in check_candidates:
                _check_and_tally(transaction)
                checked += 1
            budget -= len(check_candidates)

        # 2. Pending transactions old enough to give up on -- no final
        # status or callback ever arrived. Measured from
        # fulfilment_received_at when we have it (that's when Hubtel's
        # own clock really started); otherwise from created_at.
        #
        # A transaction whose fulfilment we've received must NEVER be
        # given up on before it's actually been status-checked at least
        # once (last_status_check_at is not None) -- step 1a above always
        # checks it first in this very run if it's due, but this extra
        # guard also covers a transaction that, for whatever reason (the
        # sweep not having run, a bug), was never checked at all: without
        # it, a genuinely paid transaction could be flagged needs_review
        # -- effectively hiding the payment -- without Hubtel ever having
        # been asked about it. A transaction with no fulfilment at all
        # keeps the original, simpler age-only rule.
        if budget > 0:
            give_up_cutoff = now - timedelta(hours=STATUS_CHECK_GIVE_UP_HOURS)
            timeout_candidates = (
                Transaction.query
                .filter(Transaction.status == "pending")
                .filter(db.or_(
                    db.and_(
                        Transaction.fulfilment_received_at.isnot(None),
                        Transaction.fulfilment_received_at < give_up_cutoff,
                        Transaction.last_status_check_at.isnot(None),
                    ),
                    db.and_(
                        Transaction.fulfilment_received_at.is_(None),
                        Transaction.created_at < give_up_cutoff,
                    ),
                ))
                .order_by(Transaction.created_at)
                .limit(budget)
                .all()
            )
            for transaction in timeout_candidates:
                transaction.needs_review = True
                transaction.review_reason = (
                    "fulfilment received but not confirmed after 24 hours"
                    if transaction.fulfilment_received_at is not None
                    else "no final status after 24 hours"
                )
            if timeout_candidates:
                db.session.commit()
            timed_out = len(timeout_candidates)
            budget -= timed_out

        # 3. 'success' transactions whose final callback hasn't gone out
        # yet: every run for the first CALLBACK_FAST_RETRY_MINUTES after
        # fulfilment, then every CALLBACK_RETRY_COOLDOWN_MINUTES.
        # send_final_callback itself enforces the real one-hour deadline
        # and flags needs_review if we run out of time, so this query
        # only needs to decide WHEN to make another attempt.
        if budget > 0:
            callback_fast_cutoff = now - timedelta(minutes=CALLBACK_FAST_RETRY_MINUTES)
            callback_slow_cutoff = now - timedelta(minutes=CALLBACK_RETRY_COOLDOWN_MINUTES)
            callback_candidates = (
                Transaction.query
                .filter(Transaction.status == "success")
                .filter(Transaction.callback_sent_at.is_(None))
                .filter(Transaction.needs_review.is_(False))
                .filter(Transaction.callback_attempts < MAX_CALLBACK_ATTEMPTS)
                .filter(db.or_(
                    Transaction.fulfilment_received_at.is_(None),
                    Transaction.fulfilment_received_at >= callback_fast_cutoff,
                    Transaction.callback_last_attempt_at.is_(None),
                    Transaction.callback_last_attempt_at < callback_slow_cutoff,
                ))
                .order_by(Transaction.created_at)
                .limit(budget)
                .all()
            )
            for transaction in callback_candidates:
                send_final_callback(transaction.id)
                retried += 1

        click.echo(
            f"hubtel-sweep: checked {checked} "
            f"(paid {outcome_counts['paid']}, unpaid {outcome_counts['unpaid']}, "
            f"refunded {outcome_counts['refunded']}, unknown {outcome_counts['unknown']}, "
            f"error {outcome_counts['error']}), "
            f"timed out {timed_out}, retried callback {retried}"
        )
