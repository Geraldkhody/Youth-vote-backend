"""add transactions and votes tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('transactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('reference', sa.String(length=20), nullable=False),
    sa.Column('channel', sa.Enum('ussd', 'web', name='transaction_channel'), nullable=False),
    sa.Column('hubtel_session_id', sa.String(length=100), nullable=True),
    sa.Column('nominee_id', sa.Integer(), nullable=False),
    sa.Column('phone', sa.String(length=12), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit_fee_pesewas', sa.Integer(), nullable=False),
    sa.Column('amount_pesewas', sa.BigInteger(), nullable=False),
    sa.Column('provider_total_pesewas', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.Enum('pending', 'success', 'failed', 'cancelled', name='transaction_status'), nullable=False),
    sa.Column('needs_review', sa.Boolean(), nullable=False),
    sa.Column('review_reason', sa.Text(), nullable=True),
    sa.Column('provider_payload', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('quantity > 0', name='ck_transactions_quantity_positive'),
    sa.CheckConstraint('unit_fee_pesewas > 0', name='ck_transactions_fee_positive'),
    sa.CheckConstraint('amount_pesewas = quantity * unit_fee_pesewas', name='ck_transactions_amount_matches_quantity_times_fee'),
    sa.ForeignKeyConstraint(['nominee_id'], ['nominees.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('reference'),
    sa.UniqueConstraint('hubtel_session_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )

    op.create_table('votes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transaction_id', sa.Integer(), nullable=False),
    sa.Column('nominee_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('quantity > 0', name='ck_votes_quantity_positive'),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['nominee_id'], ['nominees.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('transaction_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )


def downgrade():
    op.drop_table('votes')
    op.drop_table('transactions')
