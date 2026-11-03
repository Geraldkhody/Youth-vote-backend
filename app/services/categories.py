from app.extensions import db
from app.models.category import Category
from app.models.nomination import Nomination
from app.models.nominee import Nominee
from app.services.audit import log_audit


def create_category(name, code_letter, description=None):
    """Create a new category. Raises ValueError for bad input.

    name must not be empty. code_letter must be a single A-Z letter that
    isn't already used by another category.
    """
    name = (name or "").strip()
    code_letter = (code_letter or "").strip().upper()

    if not name:
        raise ValueError("name is required")

    if len(code_letter) != 1 or not code_letter.isalpha():
        raise ValueError("code_letter must be a single letter A-Z")

    if Category.query.filter_by(code_letter=code_letter).first() is not None:
        raise ValueError(f"code_letter '{code_letter}' is already in use")

    category = Category(name=name, code_letter=code_letter, description=description)
    db.session.add(category)
    db.session.flush()  # assigns category.id, without committing yet
    log_audit("category.create", "category", category.id, {"name": name, "code_letter": code_letter})
    db.session.commit()

    return category


def can_change_code_letter(category):
    """Whether a category's code_letter is still safe to change.

    Once a category has nominations (pending or otherwise) or nominees,
    changing its letter would make past codes (e.g. "A47") confusing or
    wrong, so it's only allowed while the category is brand new.
    """
    has_nominations = Nomination.query.filter_by(category_id=category.id).first() is not None
    has_nominees = Nominee.query.filter_by(category_id=category.id).first() is not None
    return not has_nominations and not has_nominees


def update_category(category, name=None, description=None, is_active=None, code_letter=None):
    """Update a category's fields. Each argument is only applied if it was
    actually passed (so a PATCH can send just one field).

    Raises ValueError for bad input: an empty name, a code_letter change on
    a category that already has nominations/nominees, or a code_letter
    already used by another category.

    Deactivating (is_active=False) never deletes anything -- there is no
    delete endpoint. A category with nominations must be kept around so
    those nominations' history still makes sense, so it can only be hidden
    from the public categories list, not removed.
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
        if len(code_letter) != 1 or not code_letter.isalpha():
            raise ValueError("code_letter must be a single letter A-Z")
        if code_letter != category.code_letter:
            if not can_change_code_letter(category):
                raise ValueError("code_letter cannot be changed once the category has nominations or nominees")
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
