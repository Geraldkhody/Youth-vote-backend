from datetime import datetime, timezone

from app.extensions import db


class Nominee(db.Model):
    """A nominee created once a nomination is approved.

    The (category_id, code) pair is unique: the same code can be reused
    across different categories, but never twice within one category.
    """

    __tablename__ = "nominees"
    __table_args__ = (
        db.UniqueConstraint("category_id", "code", name="uq_nominees_category_code"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)

    code = db.Column(db.String(5), nullable=False)  # e.g. "B47" or "YTH47"
    full_name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(12), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    deactivation_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    category = db.relationship("Category")

    def to_dict(self):
        """Full representation, including the phone number. Admin-only."""
        return {
            "id": self.id,
            "category_id": self.category_id,
            "code": self.code,
            "full_name": self.full_name,
            "phone": self.phone,
            "is_active": self.is_active,
            "deactivation_reason": self.deactivation_reason,
            "created_at": self.created_at.isoformat(),
        }

    def to_public_dict(self):
        """Public representation: no phone number, for the open nominee list."""
        return {
            "id": self.id,
            "category_id": self.category_id,
            "code": self.code,
            "full_name": self.full_name,
        }
