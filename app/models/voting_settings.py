from datetime import datetime, timezone

from app.extensions import db


def _isoformat_utc(value):
    """Format a naive datetime (always stored as a UTC instant) as ISO
    text with an explicit "Z", so API consumers know it's UTC despite the
    database column itself having no timezone of its own."""
    return value.isoformat() + "Z" if value else None


class VotingSettings(db.Model):
    """The single row of voting configuration: the fee, the voting window,
    and whether voting is paused.

    This is a single-row table -- there is always exactly one row, and its
    id is always 1. Use get_settings() to fetch it (it creates the row with
    defaults the first time it's needed), rather than querying the model
    directly.

    Hubtel adds its own charge on top of the vote amount automatically, so
    this system stores and sends only the vote amount -- never Hubtel's
    charge, and never a combined total.
    """

    __tablename__ = "voting_settings"
    __table_args__ = (
        db.CheckConstraint("vote_fee_pesewas > 0", name="ck_voting_settings_fee_positive"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id = db.Column(db.Integer, primary_key=True)

    vote_fee_pesewas = db.Column(db.Integer, nullable=False, default=100)

    # Always UTC. Nullable because voting might not be scheduled yet.
    voting_opens_at = db.Column(db.DateTime, nullable=True)
    voting_closes_at = db.Column(db.DateTime, nullable=True)

    voting_paused = db.Column(db.Boolean, nullable=False, default=False)

    updated_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # RESTRICT: an admin who last changed the settings can't be deleted
    # while this row still points at them.
    updated_by = db.Column(db.Integer, db.ForeignKey("admin_users.id", ondelete="RESTRICT"), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "vote_fee_pesewas": self.vote_fee_pesewas,
            "voting_opens_at": _isoformat_utc(self.voting_opens_at),
            "voting_closes_at": _isoformat_utc(self.voting_closes_at),
            "voting_paused": self.voting_paused,
            "updated_at": _isoformat_utc(self.updated_at),
            "updated_by": self.updated_by,
        }


# The row id used by the single-row table. Always 1.
SETTINGS_ROW_ID = 1


def get_settings():
    """Return the one VotingSettings row, creating it with defaults first
    if it doesn't exist yet (e.g. right after a fresh migration)."""
    settings = VotingSettings.query.get(SETTINGS_ROW_ID)
    if settings is None:
        settings = VotingSettings(id=SETTINGS_ROW_ID)
        db.session.add(settings)
        db.session.commit()

    return settings
