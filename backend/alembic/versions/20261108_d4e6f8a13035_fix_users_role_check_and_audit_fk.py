"""fix users.ck_users_role (3 -> 13 roles) and audit_logs.user_id FK type

Revision ID: d4e6f8a13035
Revises: c3d5e7f92024
Create Date: 2026-11-08 09:40:00.000000

Hai drift giua models.py va migration, ca hai deu vo hinh tren CI:

1. `ck_users_role` o initial schema chi liet ke 3 vai truyen thong. Pillar-2 them
   L1..L10 vao enum `Role` va models.py sinh constraint tu enum (13 vai), nhung
   migration van dong cung 3 vai. SQLite dev dung `create_all()` (lay tu model, 13
   vai) nen moi thu xanh; Postgres prod dung alembic (3 vai) nen INSERT bat ky user
   L1..L10 nao cung vi pham CHECK. `alembic upgrade head` van thanh cong vi tao
   constraint sai khong phai la loi - loi chi lo ra luc runtime, sau rollout.

2. `audit_logs.user_id` duoc tao bang `sa.Integer()` trong khi `users.id` la
   `BigInteger().with_variant(Integer, 'sqlite')`. Tren Postgres model cho BIGINT
   con migration cho INTEGER. FK int4->int8 van duoc Postgres chap nhan nen khong
   bao loi, nhung dev va prod chay hai schema khac nhau.

Khong sua nguoc migration cu: DB nao da upgrade roi thi phai co mot buoc tien
len de sua, con cai dat moi chay het chuoi roi cung ra ket qua dung.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e6f8a13035'
down_revision: Union[str, None] = 'c3d5e7f92024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Dong dung cu phap models.py sinh ra (', '.join(repr(r.value))) de `alembic check`
# khong thay drift. Danh sach nay la anh chup cua enum tai thoi diem viet migration:
# them vai moi thi phai viet migration moi, khong sua file nay.
_ALL_ROLES = (
    'BGD', 'VANHANH', 'KETOAN',
    'L1_CHAIRMAN', 'L2_CEO',
    'L3_TECHNICAL_DIRECTOR', 'L4_OPERATIONS_MANAGER', 'L5_MAINTENANCE_ENGINEER',
    'L6_HACCP_AUDITOR', 'L7_WAREHOUSE_DISPATCHER',
    'L8_CFO', 'L9_BILLING_SPECIALIST', 'L10_SALES_EXECUTIVE',
)

_LEGACY_ROLES = ('BGD', 'VANHANH', 'KETOAN')


def _in_clause(roles: Sequence[str]) -> sa.TextClause:
    return sa.text("role IN ({})".format(', '.join(repr(r) for r in roles)))


def _fk_name_for(table: str, column: str, referred: str) -> Union[str, None]:
    """Postgres tu dat ten FK (khong khai bao ten trong migration goc) nen phai hoi DB."""
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if fk.get("constrained_columns") == [column] and fk.get("referred_table") == referred:
            return fk.get("name")
    return None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    big_int_pk = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')

    # --- 1. users.ck_users_role: 3 vai -> 13 vai -------------------------- #
    if dialect == 'postgresql':
        op.drop_constraint('ck_users_role', 'users', type_='check')
        op.create_check_constraint('ck_users_role', 'users', _in_clause(_ALL_ROLES))
    else:
        # SQLite khong ALTER duoc constraint: phai de batch mode dung lai bang.
        with op.batch_alter_table('users', recreate='always') as batch:
            batch.drop_constraint('ck_users_role', type_='check')
            batch.create_check_constraint('ck_users_role', _in_clause(_ALL_ROLES))

    # --- 2. audit_logs.user_id: INTEGER -> BIGINT --------------------------- #
    if dialect == 'postgresql':
        # Postgres khong doi kieu cot dang nam trong FK: go FK, doi kieu, gan lai.
        fk_name = _fk_name_for('audit_logs', 'user_id', 'users')
        if fk_name:
            op.drop_constraint(fk_name, 'audit_logs', type_='foreignkey')
        op.alter_column(
            'audit_logs', 'user_id',
            existing_type=sa.Integer(), type_=sa.BigInteger(),
            existing_nullable=True,
        )
        op.create_foreign_key(
            fk_name or 'audit_logs_user_id_fkey',
            'audit_logs', 'users', ['user_id'], ['id'],
        )
    else:
        with op.batch_alter_table('audit_logs', recreate='always') as batch:
            batch.alter_column(
                'user_id',
                existing_type=sa.Integer(), type_=big_int_pk,
                existing_nullable=True,
            )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == 'postgresql':
        fk_name = _fk_name_for('audit_logs', 'user_id', 'users')
        if fk_name:
            op.drop_constraint(fk_name, 'audit_logs', type_='foreignkey')
        op.alter_column(
            'audit_logs', 'user_id',
            existing_type=sa.BigInteger(), type_=sa.Integer(),
            existing_nullable=True,
        )
        op.create_foreign_key(
            fk_name or 'audit_logs_user_id_fkey',
            'audit_logs', 'users', ['user_id'], ['id'],
        )
        op.drop_constraint('ck_users_role', 'users', type_='check')
        op.create_check_constraint('ck_users_role', 'users', _in_clause(_LEGACY_ROLES))
    else:
        with op.batch_alter_table('audit_logs', recreate='always') as batch:
            batch.alter_column(
                'user_id',
                existing_type=sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                type_=sa.Integer(),
                existing_nullable=True,
            )
        with op.batch_alter_table('users', recreate='always') as batch:
            batch.drop_constraint('ck_users_role', type_='check')
            batch.create_check_constraint('ck_users_role', _in_clause(_LEGACY_ROLES))
