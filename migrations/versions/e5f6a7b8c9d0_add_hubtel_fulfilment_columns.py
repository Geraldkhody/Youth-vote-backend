"""add hubtel fulfilment/callback columns to transactions

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('hubtel_order_id', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('fulfilment_received_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('last_status_check_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('callback_sent_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('callback_attempts', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('callback_last_attempt_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('callback_last_error', sa.Text(), nullable=True))
        batch_op.create_index('ix_transactions_hubtel_order_id', ['hubtel_order_id'])


def downgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_index('ix_transactions_hubtel_order_id')
        batch_op.drop_column('callback_last_error')
        batch_op.drop_column('callback_last_attempt_at')
        batch_op.drop_column('callback_attempts')
        batch_op.drop_column('callback_sent_at')
        batch_op.drop_column('last_status_check_at')
        batch_op.drop_column('fulfilment_received_at')
        batch_op.drop_column('hubtel_order_id')
