from datetime import datetime, timezone

from app.extensions import db


class AuditLog(db.Model):
    """A record of an admin action (who did what, to what, and when).

    Audit rows are never edited or deleted -- this model intentionally has
    no update or delete methods. Once written, a row stays exactly as it
    was written, forever.
    """

    __tablename__ = "audit_logs"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    id = db.Column(db.Integer, primary_key=True)

    # Nullable: some actions (e.g. a system job) might not have an admin.
    # ondelete="RESTRICT" means an admin can't be deleted while audit rows
    # still reference them -- audit history must never be able to vanish.
    admin_id = db.Column(db.Integer, db.ForeignKey("admin_users.id", ondelete="RESTRICT"), nullable=True)

    action = db.Column(db.String(100), nullable=False)  # e.g. "nomination.approve"
    entity_type = db.Column(db.String(50), nullable=False)  # e.g. "nomination"
    entity_id = db.Column(db.Integer, nullable=False)
    details = db.Column(db.JSON, nullable=True)  # e.g. {"phone": {"before": "...", "after": "..."}}
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    admin = db.relationship("AdminUser")

    def to_dict(self):
        return {
            "id": self.id,
            "admin_id": self.admin_id,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "details": self.details,
            "created_at": self.created_at.isoformat(),
        }
