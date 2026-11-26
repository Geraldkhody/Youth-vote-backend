"""add voting_settings table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('voting_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('vote_fee_pesewas', sa.Integer(), nullable=False),
    sa.Column('voting_opens_at', sa.DateTime(), nullable=True),
    sa.Column('voting_closes_at', sa.DateTime(), nullable=True),
    sa.Column('voting_paused', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.CheckConstraint('vote_fee_pesewas > 0', name='ck_voting_settings_fee_positive'),
    sa.ForeignKeyConstraint(['updated_by'], ['admin_users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )


def downgrade():
    op.drop_table('voting_settings')
