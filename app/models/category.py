from datetime import datetime, timezone

from app.extensions import db


class Category(db.Model):
    """An award category, e.g. 'A' for 'Youth Leader of the Year'."""

    __tablename__ = "categories"

    # Setting the charset/collation here (not just at the database level) means
    # it's recorded in the migration, so it's explicit and reproducible, and it
    # works the same on MariaDB and MySQL since both use the "mysql" dialect
    # via PyMySQL.
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)

    # One to three letters (A-Z) used to label the category, e.g. in ballots.
    code_letter = db.Column(db.String(3), nullable=False, unique=True)

    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        """Convert the model into a plain dict so it can be returned as JSON."""
        return {
            "id": self.id,
            "name": self.name,
            "code_letter": self.code_letter,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }
