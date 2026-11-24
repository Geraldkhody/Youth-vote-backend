"""add hubtel_logs table

Revision ID: a1b2c3d4e5f6
Revises: 6063ddb479a8
Create Date: 2026-11-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '6063ddb479a8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('hubtel_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.Column('body', sa.JSON(), nullable=True),
    sa.Column('response_status', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )


def downgrade():
    op.drop_table('hubtel_logs')
