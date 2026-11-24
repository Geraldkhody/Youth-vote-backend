from datetime import datetime, timezone

from app.extensions import db


class HubtelLog(db.Model):
    """A raw record of requests Hubtel's Programmable Services sent us.

    This exists only to prove the stub endpoints work and to see Hubtel's
    real request shapes during the test period. It is NOT part of the
    permanent audit trail (see AuditLog for that) and must be reviewed and
    pruned before going live.
    """

    __tablename__ = "hubtel_logs"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)  # "interaction" or "fulfillment"
    received_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    body = db.Column(db.JSON, nullable=True)
    response_status = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "received_at": self.received_at.isoformat(),
            "body": self.body,
            "response_status": self.response_status,
        }
