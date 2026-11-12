from app.extensions import db
from app.models.category import Category
from app.models.nomination import Nomination
from app.models.nominee import Nominee
from app.services.audit import log_audit


def create_category(name, code_letter, description=None):
    """Create a new category. Raises ValueError for bad input.

    name must not be empty. code_letter must be 1-3 A-Z letters that
    aren't already used by another category.
    """
    name = (name or "").strip()
    code_letter = (code_letter or "").strip().upper()

    if not name:
        raise ValueError("name is required")

    if not (1 <= len(code_letter) <= 3) or not code_letter.isalpha():
        raise ValueError("code_letter must be 1-3 letters A-Z")

    if Category.query.filter_by(code_letter=code_letter).first() is not None:
        raise ValueError(f"code_letter '{code_letter}' is already in use")

    category = Category(name=name, code_letter=code_letter, description=description)
    db.session.add(category)
    db.session.flush()  # assigns category.id, without committing yet
    log_audit("category.create", "category", category.id, {"name": name, "code_letter": code_letter})
    db.session.commit()

    return category


def update_category(category, name=None, description=None, is_active=None, code_letter=None):
    """Update a category's fields. Each argument is only applied if it was
    actually passed (so a PATCH can send just one field).

    Raises ValueError for bad input: an empty name or a code_letter already
    used by another category. code_letter can be changed at any time, even
    once the category has nominations or nominees -- existing nominee codes
    (e.g. "A47") keep their own letter and aren't renamed to match.

    Deactivating (is_active=False) hides the category from the public list
    without removing it or anything linked to it -- use delete_category to
    remove it permanently.
    """
    changes = {}  # before/after values, for the audit row

    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("name must not be empty")
        if name != category.name:
            changes["name"] = {"before": category.name, "after": name}
            category.name = name

    if description is not None and description != category.description:
        changes["description"] = {"before": category.description, "after": description}
        category.description = description

    if code_letter is not None:
        code_letter = code_letter.strip().upper()
        if not (1 <= len(code_letter) <= 3) or not code_letter.isalpha():
            raise ValueError("code_letter must be 1-3 letters A-Z")
        if code_letter != category.code_letter:
            existing = Category.query.filter_by(code_letter=code_letter).first()
            if existing is not None and existing.id != category.id:
                raise ValueError(f"code_letter '{code_letter}' is already in use")
            changes["code_letter"] = {"before": category.code_letter, "after": code_letter}
            category.code_letter = code_letter

    if is_active is not None and is_active != category.is_active:
        changes["is_active"] = {"before": category.is_active, "after": is_active}
        category.is_active = is_active

    if changes:
        log_audit("category.update", "category", category.id, changes)

    db.session.commit()

    return category


def delete_category(category):
    """Permanently delete a category, along with its nominations and
    nominees.

    This is a deliberate exception to the usual "deactivate, never delete"
    rule, requested for categories specifically. It's a hard delete: any
    nominations and nominees in this category are removed too, since they
    can't be kept around without the category they belong to, and that
    history is lost for good. The audit row is written first, while the
    category still exists, so the deletion itself stays on record.
    """
    log_audit("category.delete", "category", category.id, {
        "name": category.name,
        "code_letter": category.code_letter,
    })

    # Nominations reference nominees, so they must go first, then nominees,
    # then the category itself -- otherwise the foreign keys would block it.
    Nomination.query.filter_by(category_id=category.id).delete()
    Nominee.query.filter_by(category_id=category.id).delete()
    db.session.delete(category)

    db.session.commit()
