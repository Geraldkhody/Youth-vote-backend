from datetime import datetime, timezone

from app.extensions import db


class Vote(db.Model):
    """One recorded vote, created from exactly one successful Transaction.

    Votes are never updated or deleted -- this model intentionally has no
    update or delete helpers, the same way AuditLog works. A database-level
    protection step (e.g. revoking UPDATE/DELETE on this table) comes
    later; for now this is enforced only by convention and by
    record_successful_payment() being the sole place that creates a row.
    """

    __tablename__ = "votes"
    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_votes_quantity_positive"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id = db.Column(db.Integer, primary_key=True)

    # UNIQUE: at most one vote per transaction, ever. This is the last
    # line of defence against double-voting -- see record_successful_payment().
    transaction_id = db.Column(
        db.Integer, db.ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False, unique=True,
    )
    nominee_id = db.Column(db.Integer, db.ForeignKey("nominees.id", ondelete="RESTRICT"), nullable=False)

    quantity = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    transaction = db.relationship("Transaction")
    nominee = db.relationship("Nominee")

    def to_dict(self):
        return {
            "id": self.id,
            "transaction_id": self.transaction_id,
            "nominee_id": self.nominee_id,
            "quantity": self.quantity,
            "created_at": self.created_at.isoformat(),
        }
