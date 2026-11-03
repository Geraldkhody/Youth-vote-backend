from datetime import datetime, timezone

from app.extensions import db
from app.services.audit import log_audit
from app.utils import normalize_phone


def deactivate_nominee(nominee, reason):
    """Mark a nominee as inactive, recording why. Does not delete anything."""
    if not nominee.is_active:
        raise ValueError("nominee is already inactive")

    nominee.is_active = False
    nominee.deactivation_reason = reason
    log_audit("nominee.deactivate", "nominee", nominee.id, {"reason": reason})
    db.session.commit()


def edit_nominee(nominee, full_name=None, phone=None):
    """Update a nominee's full_name and/or phone.

    Each argument is only applied if it was actually passed (so a PATCH can
    send just one field). Raises ValueError for bad input: an empty name, an
    unrecognised phone format, or editing an inactive nominee.
    """
    if not nominee.is_active:
        raise ValueError("cannot edit an inactive nominee")

    changes = {}  # before/after values, for the audit row

    if full_name is not None:
        full_name = full_name.strip()
        if not full_name:
            raise ValueError("full_name must not be empty")
        if full_name != nominee.full_name:
            changes["full_name"] = {"before": nominee.full_name, "after": full_name}
            nominee.full_name = full_name

    if phone is not None:
        normalized_phone = normalize_phone(phone)
        if normalized_phone is None:
            raise ValueError("phone must be in the format 0XXXXXXXXX, 233XXXXXXXXX or +233XXXXXXXXX")
        if normalized_phone != nominee.phone:
            changes["phone"] = {"before": nominee.phone, "after": normalized_phone}
            nominee.phone = normalized_phone

    if changes:
        log_audit("nominee.edit", "nominee", nominee.id, changes)

    db.session.commit()


def merge_nomination_into_nominee(nomination, nominee):
    """Attach a pending nomination to an existing nominee instead of
    creating a new one -- for duplicate submissions of the same person.

    On success the nomination is marked "approved" and linked to the
    nominee. Raises ValueError if the nomination isn't pending, the
    nominee isn't active, or they're in different categories.
    """
    if nomination.status != "pending":
        raise ValueError(f"only pending nominations can be merged (this one is '{nomination.status}')")

    if not nominee.is_active:
        raise ValueError("cannot merge into an inactive nominee")

    if nominee.category_id != nomination.category_id:
        raise ValueError("nominee must be in the same category as the nomination")

    nomination.status = "approved"
    nomination.nominee_id = nominee.id
    nomination.reviewed_at = datetime.now(timezone.utc)
    log_audit("nomination.merge", "nomination", nomination.id, {"nominee_id": nominee.id})
    db.session.commit()
