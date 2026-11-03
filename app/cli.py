import click

from app.extensions import db
from app.models.admin_user import AdminUser


def register_cli(app):
    """Register custom `flask` CLI commands on the app."""

    @app.cli.command("create-admin")
    def create_admin():
        """Interactively create an admin user (flask create-admin)."""
        name = click.prompt("Name")
        email = click.prompt("Email").strip()
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)

        existing = AdminUser.query.filter_by(email=email).first()
        if existing is not None:
            click.echo(f"Error: an admin with email '{email}' already exists.")
            return

        admin = AdminUser(name=name, email=email, is_active=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()

        click.echo(f"Admin '{name}' ({email}) created.")
