from flask import g

from app.extensions import db
from app.models.audit_log import AuditLog


def log_audit(action, entity_type, entity_id, details=None, admin_id=None):
    """Record an audit row for the admin currently logged in (if any).

    admin_id normally comes from flask.g.admin_id, set by @admin_required
    for the current request. Pass it explicitly for the rare case where
    there's no token yet to read it from -- e.g. logging the login action
    itself, right after the password check succeeds.

    This does NOT call db.session.commit() -- it only adds the row to the
    session. The caller commits afterwards, so the audit row is saved in
    the exact same database transaction as the change it records. That way,
    if that transaction fails, the audit row never gets saved either.
    """
    if admin_id is None:
        admin_id = getattr(g, "admin_id", None)

    log = AuditLog(
        admin_id=admin_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.session.add(log)
