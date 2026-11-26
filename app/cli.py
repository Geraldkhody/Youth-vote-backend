from datetime import datetime, timedelta, timezone

import click

from app.extensions import db
from app.models.admin_user import AdminUser
from app.models.transaction import Transaction
from app.services.hubtel_fulfilment import MAX_CALLBACK_ATTEMPTS, process_hubtel_payment, send_final_callback

# Total items this command will touch in one run, across all three
# checks combined -- a cron job calling this every minute should never
# need to chew through more than this in one go.
SWEEP_ITEM_LIMIT = 50


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

        # 1. Pending transactions old enough to check, not checked too recently.
        check_candidates = (
            Transaction.query
            .filter(Transaction.status == "pending")
            .filter(Transaction.hubtel_session_id.isnot(None))
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
            process_hubtel_payment(transaction.id)
            checked += 1
        budget -= checked

        # 2. Pending transactions old enough to give up on -- no final
        # status or callback ever arrived.
        if budget > 0:
            timeout_candidates = (
                Transaction.query
                .filter(Transaction.status == "pending")
                .filter(Transaction.created_at < now - timedelta(hours=24))
                .order_by(Transaction.created_at)
                .limit(budget)
                .all()
            )
            for transaction in timeout_candidates:
                transaction.needs_review = True
                transaction.review_reason = "no final status after 24 hours"
            if timeout_candidates:
                db.session.commit()
            timed_out = len(timeout_candidates)
            budget -= timed_out

        # 3. 'success' transactions whose final callback hasn't gone out yet.
        if budget > 0:
            callback_candidates = (
                Transaction.query
                .filter(Transaction.status == "success")
                .filter(Transaction.callback_sent_at.is_(None))
                .filter(Transaction.callback_attempts < MAX_CALLBACK_ATTEMPTS)
                .filter(db.or_(
                    Transaction.callback_last_attempt_at.is_(None),
                    Transaction.callback_last_attempt_at < now - timedelta(minutes=5),
                ))
                .order_by(Transaction.created_at)
                .limit(budget)
                .all()
            )
            for transaction in callback_candidates:
                send_final_callback(transaction.id)
                retried += 1

        click.echo(f"hubtel-sweep: checked {checked}, timed out {timed_out}, retried callback {retried}")
