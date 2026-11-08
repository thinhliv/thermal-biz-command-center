"""add outdoor_weather_samples table

Revision ID: f6a7b8c9d0e1
Revises: e5f7a9b24168
Create Date: 2026-11-08 17:00:00.000000

Bang luu du lieu khi tuong / nhiet do moi truong ngoai troi cho tung co so (Site).
Phuc vu chuan hoa dien nang theo nhiet do moi truong (IPMVP Option B/C) va tinh
toan Degree Days (CDD/CDH), chong nguyen tac bia du lieu / dung nhiet do buong
lam proxy cho moi truong.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f7a9b24168'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'outdoor_weather_samples',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('site_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('site_code', sa.String(length=32), nullable=False),
        sa.Column('ts', sa.DateTime(), nullable=False),
        sa.Column('ambient_temperature_c', sa.Float(), nullable=False),
        sa.Column('relative_humidity_pct', sa.Float(), nullable=True),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('station_id', sa.String(length=64), nullable=True),
        sa.Column('is_measured', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('site_id', 'ts', name='uq_outdoor_weather_site_ts'),
    )
    op.create_index(op.f('ix_outdoor_weather_samples_site_id'), 'outdoor_weather_samples', ['site_id'], unique=False)
    op.create_index(op.f('ix_outdoor_weather_samples_site_code'), 'outdoor_weather_samples', ['site_code'], unique=False)
    op.create_index(op.f('ix_outdoor_weather_samples_ts'), 'outdoor_weather_samples', ['ts'], unique=False)
    op.create_index('ix_outdoor_weather_site_ts', 'outdoor_weather_samples', ['site_id', 'ts'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_outdoor_weather_site_ts', table_name='outdoor_weather_samples')
    op.drop_index(op.f('ix_outdoor_weather_samples_ts'), table_name='outdoor_weather_samples')
    op.drop_index(op.f('ix_outdoor_weather_samples_site_code'), table_name='outdoor_weather_samples')
    op.drop_index(op.f('ix_outdoor_weather_samples_site_id'), table_name='outdoor_weather_samples')
    op.drop_table('outdoor_weather_samples')
