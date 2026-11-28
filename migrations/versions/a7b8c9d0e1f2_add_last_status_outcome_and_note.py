"""add last_status_outcome and last_status_note to transactions

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column(
            'last_status_outcome', sa.String(length=20), nullable=True,
        ))
        batch_op.add_column(sa.Column(
            'last_status_note', sa.String(length=255), nullable=True,
        ))


def downgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('last_status_note')
        batch_op.drop_column('last_status_outcome')
