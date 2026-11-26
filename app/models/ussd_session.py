from datetime import datetime, timezone

from app.extensions import db


class UssdSession(db.Model):
    """Server-side memory of where a voter is in the USSD menu.

    Hubtel's ClientState is NOT relied on for anything important -- it's
    only ever echoed back once on the next request and then gone, which
    makes it unsuitable for remembering a multi-step choice. This table is
    the real source of truth for "what step is this session on, and what
    has the voter picked so far" (see app/services/ussd.py).
    """

    __tablename__ = "ussd_sessions"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    # Hubtel's own SessionId -- one USSD session, one row.
    session_id = db.Column(db.String(100), primary_key=True)

    phone = db.Column(db.String(12), nullable=False)
    step = db.Column(db.String(50), nullable=False)

    # Whatever the current step needs to remember: chosen category id,
    # nominee id, quantity, the fee shown on the confirm screen, which
    # page of a list is showing, etc. Shape differs per step, so this
    # stays schemaless rather than a column per possible field.
    data = db.Column(db.JSON, nullable=False, default=dict)

    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
