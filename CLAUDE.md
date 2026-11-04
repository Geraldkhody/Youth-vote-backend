# CLAUDE.md — Backend (Youth Awards Nomination & Voting)

## Shared rules (keep identical in both files)

### What the system does
A parish youth awards system. Public users nominate people for award categories through a web form (free). Anyone votes for approved nominees through a USSD menu and pays by Mobile Money (paid). Admins review nominations, manage nominees and categories, and see an audit log. There is also a public rankings page (no vote counts).

### Business rules
- Nominations are free. Voting is paid.
- Vote fee is one amount set by the admin, default GH₵1.00, stored in pesewas (100).
- Money is always stored as integer pesewas. Never floats.
- Nominee codes are a category letter plus two random digits from 10 to 99 (e.g. B47). Unique within a category. Never sequential.
- Phone numbers are accepted as 0XXXXXXXXX, 233XXXXXXXXX or +233XXXXXXXXX and stored as 233XXXXXXXXX.
- Nominations start as pending. Only pending nominations can be approved, rejected or merged.
- Deactivate, never delete. Nominees, categories and admins are deactivated.
- Testing: all manual testing uses port 5001. Show real terminal output and real responses, never a summary.

## Backend rules

- Flask app factory, blueprints, Flask-SQLAlchemy, Flask-Migrate, PyMySQL.
- Local database: XAMPP MariaDB (`youth_vote`). Production: MySQL 8.4. Code must work on both.
- Use `utf8mb4_unicode_ci` everywhere. No MariaDB-only or MySQL-only features.
- Routes stay thin. Business logic lives in `app/services/`.
- Every admin route uses `@admin_required` from `app/auth_utils.py`.
- Every change by an admin writes an audit row in the same transaction.
- Audit rows are never edited or deleted. The AuditLog model has no update or delete functions.
- Never store or return plain passwords or password hashes in responses or audit details.
- Public responses never include phone numbers or vote counts.
- If the API shape changes, say so, because the frontend depends on it.
- Code style: intermediate Flask. Familiar patterns, descriptive names, short functions, comments on anything non-obvious (locking, transactions, validation).

## Commands

- Run: `flask run --port 5001` (from `backend/`, with `.venv` active)
- Migrate: `flask db upgrade`
- Test: `python -m pytest`
