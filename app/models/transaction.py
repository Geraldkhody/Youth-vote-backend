from datetime import datetime, timezone

from app.extensions import db


class Transaction(db.Model):
    """One attempt to buy votes for a nominee, whether it succeeds or not.

    A Transaction always starts 'pending'. Only record_successful_payment()
    (app/services/transactions.py) is allowed to move one to 'success' and
    create the matching Vote -- see that function for the full rules.

    amount_pesewas is the vote amount ONLY. Hubtel adds its own charge on
    top automatically when the voter pays, so we never store or send a
    combined total -- provider_total_pesewas (below) is Hubtel's real total
    including their charge, kept purely for reconciliation/reporting.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_transactions_quantity_positive"),
        db.CheckConstraint("unit_fee_pesewas > 0", name="ck_transactions_fee_positive"),
        db.CheckConstraint(
            "amount_pesewas = quantity * unit_fee_pesewas",
            name="ck_transactions_amount_matches_quantity_times_fee",
        ),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id = db.Column(db.Integer, primary_key=True)

    # Our own id for this transaction, e.g. "VAB12CD34EF56" -- "V" plus 12
    # random uppercase letters/digits. Safe to show to a voter or Hubtel.
    reference = db.Column(db.String(20), nullable=False, unique=True)

    channel = db.Column(db.Enum("ussd", "web", name="transaction_channel"), nullable=False)

    # Hubtel's own id for the USSD session this payment came from. Nullable
    # because a 'web' channel transaction won't have one.
    # VERIFY later (once the real USSD flow is built): that Hubtel's
    # session id is actually the right key to look a transaction up by --
    # for now this column just reserves the slot.
    hubtel_session_id = db.Column(db.String(100), nullable=True, unique=True)

    nominee_id = db.Column(db.Integer, db.ForeignKey("nominees.id", ondelete="RESTRICT"), nullable=False)

    # 233XXXXXXXXX, same format as Nominee.phone.
    phone = db.Column(db.String(12), nullable=False)

    quantity = db.Column(db.Integer, nullable=False)

    # The fee read from VotingSettings at the moment this transaction was
    # created -- frozen here so a later fee change never changes what an
    # already-created transaction is worth.
    unit_fee_pesewas = db.Column(db.Integer, nullable=False)

    # quantity * unit_fee_pesewas, enforced by the CHECK constraint above.
    # BigInteger because this is the column calculate_vote_amount() guards
    # against overflowing.
    amount_pesewas = db.Column(db.BigInteger, nullable=False)

    # Hubtel's real total, including their own charge. For reports only --
    # never used to decide whether a vote should be created.
    provider_total_pesewas = db.Column(db.BigInteger, nullable=True)

    status = db.Column(
        db.Enum("pending", "success", "failed", "cancelled", name="transaction_status"),
        nullable=False, default="pending",
    )

    # Set when something about this transaction needs a human to look at
    # it (e.g. a wrong payment amount) -- see record_successful_payment().
    needs_review = db.Column(db.Boolean, nullable=False, default=False)
    review_reason = db.Column(db.Text, nullable=True)

    # The raw payload from whichever provider confirmed/updated this
    # transaction, kept for debugging -- not used for any decision.
    provider_payload = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    confirmed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Hubtel's own order id, learned from the fulfilment request -- needed
    # to send the final callback (see app/services/hubtel_fulfilment.py).
    hubtel_order_id = db.Column(db.String(100), nullable=True, index=True)

    fulfilment_received_at = db.Column(db.DateTime, nullable=True)
    last_status_check_at = db.Column(db.DateTime, nullable=True)

    # The final callback to Hubtel: sent at most once, for a 'success'
    # transaction only. callback_last_attempt_at also doubles as a claim
    # token so two overlapping attempts can't both send it -- see
    # send_final_callback() for how.
    callback_sent_at = db.Column(db.DateTime, nullable=True)
    callback_attempts = db.Column(db.Integer, nullable=False, default=0)
    callback_last_attempt_at = db.Column(db.DateTime, nullable=True)
    callback_last_error = db.Column(db.Text, nullable=True)

    nominee = db.relationship("Nominee")

    def to_dict(self):
        return {
            "id": self.id,
            "reference": self.reference,
            "channel": self.channel,
            "hubtel_session_id": self.hubtel_session_id,
            "nominee_id": self.nominee_id,
            "phone": self.phone,
            "quantity": self.quantity,
            "unit_fee_pesewas": self.unit_fee_pesewas,
            "amount_pesewas": self.amount_pesewas,
            "provider_total_pesewas": self.provider_total_pesewas,
            "status": self.status,
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
            "created_at": self.created_at.isoformat(),
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "updated_at": self.updated_at.isoformat(),
            "hubtel_order_id": self.hubtel_order_id,
            "fulfilment_received_at": self.fulfilment_received_at.isoformat() if self.fulfilment_received_at else None,
            "last_status_check_at": self.last_status_check_at.isoformat() if self.last_status_check_at else None,
            "callback_sent_at": self.callback_sent_at.isoformat() if self.callback_sent_at else None,
            "callback_attempts": self.callback_attempts,
            "callback_last_attempt_at": self.callback_last_attempt_at.isoformat() if self.callback_last_attempt_at else None,
            "callback_last_error": self.callback_last_error,
        }
