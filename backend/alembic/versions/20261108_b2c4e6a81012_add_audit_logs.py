"""add audit_logs table for immutable audit trail

Revision ID: b2c4e6a81012
Revises: 015f5fd51272
Create Date: 2026-11-08 01:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c4e6a81012'
down_revision: Union[str, None] = '015f5fd51272'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('user_role', sa.String(length=32), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('resource_type', sa.String(length=64), nullable=False),
        sa.Column('resource_id', sa.String(length=64), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('previous_hash', sa.String(length=64), nullable=False),
        sa.Column('signature_hash', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_signature_hash'), 'audit_logs', ['signature_hash'], unique=False)
    op.create_index(op.f('ix_audit_logs_timestamp'), 'audit_logs', ['timestamp'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_timestamp'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_signature_hash'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
