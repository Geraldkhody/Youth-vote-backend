"""add callback_claim_token to transactions

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('callback_claim_token', sa.String(length=32), nullable=True))


def downgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('callback_claim_token')
