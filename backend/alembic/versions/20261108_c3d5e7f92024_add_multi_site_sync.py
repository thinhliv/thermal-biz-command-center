"""add sites and sync_batches tables for multi-site edge-to-cloud sync engine

Revision ID: c3d5e7f92024
Revises: b2c4e6a81012
Create Date: 2026-11-08 01:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d5e7f92024'
down_revision: Union[str, None] = 'b2c4e6a81012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sites',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('location', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_sync_at', sa.DateTime(), nullable=True),
        sa.Column('sync_status', sa.String(length=20), nullable=False),
        sa.Column('sync_latency_ms', sa.Integer(), nullable=False),
        sa.Column('pending_records_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sites_code'), 'sites', ['code'], unique=True)

    op.create_table(
        'sync_batches',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('batch_id', sa.String(length=64), nullable=False),
        sa.Column('site_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('site_code', sa.String(length=32), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('records_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('idempotency_hash', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_hash')
    )
    op.create_index(op.f('ix_sync_batches_batch_id'), 'sync_batches', ['batch_id'], unique=True)
    op.create_index(op.f('ix_sync_batches_site_code'), 'sync_batches', ['site_code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_sync_batches_site_code'), table_name='sync_batches')
    op.drop_index(op.f('ix_sync_batches_batch_id'), table_name='sync_batches')
    op.drop_table('sync_batches')
    op.drop_index(op.f('ix_sites_code'), table_name='sites')
    op.drop_table('sites')
