from datetime import datetime, timezone

from app.extensions import db


class Nomination(db.Model):
    """A nomination submitted for a nominee in a given category."""

    __tablename__ = "nominations"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)

    nominee_name = db.Column(db.String(255), nullable=False)
    nominee_phone = db.Column(db.String(12), nullable=False)  # stored as 233XXXXXXXXX

    nominator_name = db.Column(db.String(255), nullable=False)
    nominator_phone = db.Column(db.String(12), nullable=False)  # stored as 233XXXXXXXXX

    # Always "pending" when created; review/approval steps change this later.
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Set once the nomination is approved, linking it to the created Nominee.
    nominee_id = db.Column(db.Integer, db.ForeignKey("nominees.id"), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    category = db.relationship("Category")
    nominee = db.relationship("Nominee")

    def to_dict(self):
        return {
            "id": self.id,
            "category_id": self.category_id,
            "nominee_name": self.nominee_name,
            "nominee_phone": self.nominee_phone,
            "nominator_name": self.nominator_name,
            "nominator_phone": self.nominator_phone,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "nominee_id": self.nominee_id,
            "rejection_reason": self.rejection_reason,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }
