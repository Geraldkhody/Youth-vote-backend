from flask import session

from app.extensions import db
from app.models.audit_log import AuditLog


def log_audit(action, entity_type, entity_id, details=None):
    """Record an audit row for the admin currently logged in (if any).

    This does NOT call db.session.commit() -- it only adds the row to the
    session. The caller commits afterwards, so the audit row is saved in
    the exact same database transaction as the change it records. That way,
    if that transaction fails, the audit row never gets saved either.
    """
    log = AuditLog(
        admin_id=session.get("admin_id"),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.session.add(log)
