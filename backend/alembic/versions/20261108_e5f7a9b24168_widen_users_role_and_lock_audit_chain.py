"""widen users.role to VARCHAR(32) and make audit_logs.previous_hash unique

Revision ID: e5f7a9b24168
Revises: d4e6f8a13035
Create Date: 2026-11-08 11:05:00.000000

Hai drift con lai giua models.py va migration, deu la loai "dev xanh, prod do":

1. `users.role` la VARCHAR(16) tu initial schema. Enum `Role` co 13 gia tri, sau
   trong so do dai hon 16 ky tu (dai nhat 23: `L5_MAINTENANCE_ENGINEER`,
   `L7_WAREHOUSE_DISPATCHER`). SQLite khong kiem tra do dai VARCHAR nen dev/test
   van xanh; Postgres chan INSERT voi "value too long for type character
   varying(16)" - tuc la 6/13 vai khong the ton tai tren prod cho toi luc nay.
   Migration d4e6f8a13035 da mo rong CHECK constraint nhung chua mo rong do dai
   cot, nen vai van bi chan o lop khac.

2. `audit_logs.previous_hash` chua co rang buoc UNIQUE. Nhat ky kiem toan la chuoi
   hash noi tiep nhau, va "moi ban ghi chi co mot ban ke nhiem" chinh la dinh
   nghia cua mot chuoi khong bi fork. Thieu rang buoc nay thi hai tien trinh ghi
   dong thoi (hoac bat ky lan doc dau chuoi nao khong duoc khoa) tao ra hai nhanh
   chuoi cung previous_hash - va fork nhin giong het bi tan cong:
   `verify_audit_chain()` bao "tampered" vinh vien ma khong ai phan biet duoc do
   loi dong bo hay do co nguoi sua nhat ky. Voi UNIQUE, no thanh mot IntegrityError
   ro rang ngay luc ghi.

LUU Y KHI CHAY TREN DB CO SAN: neu audit_logs da tung bi fork thi buoc tao UNIQUE
se dung lai voi thong bao ke ten cac id trung nhau, chu khong fail mo ho. Do la
chu dich: phai xu ly du lieu truoc (giu nhanh dung, cat nhanh sai) roi moi
upgrade tiep, vi rang buoc nay la de bao ve tinh toan ven cua nhat ky - tu dong
xoa bot ban ghi thi con nguy hon la de nguyen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e5f7a9b24168'
down_revision: Union[str, None] = 'd4e6f8a13035'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UQ_PREVIOUS_HASH = 'uq_audit_logs_previous_hash'
_OLD_ROLE_WIDTH = 16
_NEW_ROLE_WIDTH = 32


def _reject_duplicate_chain_heads() -> None:
    """Chan truoc khi tao UNIQUE, va ke ten ban ghi bi fork thay vi de DB bao loi mo ho.

    Chay cho ca SQLite lan Postgres: SQLite khong tu tao UNIQUE khi add column, va
    DB co san nao da fork thi can biet fork o dau de xu ly, khong the doan.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'audit_logs' not in inspector.get_table_names():
        return

    rows = bind.execute(
        sa.text(
            "SELECT previous_hash, COUNT(*) AS n FROM audit_logs "
            "GROUP BY previous_hash HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if not rows:
        return

    detail = []
    for previous_hash, count in rows:
        ids = bind.execute(
            sa.text(
                "SELECT id FROM audit_logs WHERE previous_hash = :ph ORDER BY id"
            ),
            {'ph': previous_hash},
        ).fetchall()
        detail.append(
            "previous_hash={!r} x{} (id: {})".format(
                previous_hash, count, ', '.join(str(row[0]) for row in ids)
            )
        )

    raise RuntimeError(
        "Khong the dat UNIQUE len audit_logs.previous_hash vi chuoi audit log dang "
        "bi fork (nhieu ban ghi cung mot previous_hash): " + '; '.join(detail) + ". "
        "Phai quyet dinh thu cong giu nhanh nao va cat nhanh nao TRUOC khi upgrade: "
        "nhat ky kiem toan khong duoc tu dong xoa ban ghi, vi xoa nham thi mat bang "
        "chung con giu thi chuoi van sai. Sau khi chi con mot nhanh, chay lai "
        "`alembic upgrade head`."
    )


def _reject_overlong_roles() -> None:
    """Chan truoc khi thu hep cot ve VARCHAR(16), ke ten user khong fit.

    Chi dung cho downgrade: Postgres se bao loi khi ALTER TYPE ma du lieu dai hon
    do dai moi, nhung thong bao do khong noi cho operator biet phai sua ai.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'users' not in inspector.get_table_names():
        return

    rows = bind.execute(
        sa.text(
            "SELECT id, username, role FROM users "
            "WHERE LENGTH(role) > :w ORDER BY id"
        ),
        {'w': _OLD_ROLE_WIDTH},
    ).fetchall()
    if not rows:
        return

    listing = ', '.join(
        "{} (id={}, role={}, {} ky tu)".format(row[1], row[0], row[2], len(row[2]))
        for row in rows
    )
    raise RuntimeError(
        f"Khong the downgrade users.role ve VARCHAR({_OLD_ROLE_WIDTH}) vi {len(rows)} "
        f"user dang giu vai dai hon: {listing}. Day khong phai loi cua migration - "
        "cac vai nay chi ton tai duoc nho schema da mo rong. Muon rollback that su "
        "thi phai doi vai cua cac user nay ve BGD/VANHANH/KETOAN truoc, va chap "
        "nhan rang ho mat quyen tuong ung."
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    # --- 1. users.role: VARCHAR(16) -> VARCHAR(32) -------------------------- #
    if dialect == 'postgresql':
        # Mo rong VARCHAR khong viet lai du lieu tren Postgres, nen khong can
        # rewrite lock; van khong doi duoc khi cot dang nam trong index bieu thuc.
        op.alter_column(
            'users', 'role',
            existing_type=sa.String(length=_OLD_ROLE_WIDTH),
            type_=sa.String(length=_NEW_ROLE_WIDTH),
            existing_nullable=False,
        )
    else:
        # SQLite khong ALTER duoc kieu cot: batch mode phai dung lai bang.
        with op.batch_alter_table('users', recreate='always') as batch:
            batch.alter_column(
                'role',
                existing_type=sa.String(length=_OLD_ROLE_WIDTH),
                type_=sa.String(length=_NEW_ROLE_WIDTH),
                existing_nullable=False,
            )

    # --- 2. audit_logs.previous_hash: UNIQUE -------------------------------- #
    _reject_duplicate_chain_heads()
    if dialect == 'postgresql':
        op.create_unique_constraint(_UQ_PREVIOUS_HASH, 'audit_logs', ['previous_hash'])
    else:
        with op.batch_alter_table('audit_logs', recreate='always') as batch:
            batch.create_unique_constraint(_UQ_PREVIOUS_HASH, ['previous_hash'])


def downgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == 'postgresql':
        op.drop_constraint(_UQ_PREVIOUS_HASH, 'audit_logs', type_='unique')
    else:
        with op.batch_alter_table('audit_logs', recreate='always') as batch:
            batch.drop_constraint(_UQ_PREVIOUS_HASH, type_='unique')

    _reject_overlong_roles()
    if dialect == 'postgresql':
        op.alter_column(
            'users', 'role',
            existing_type=sa.String(length=_NEW_ROLE_WIDTH),
            type_=sa.String(length=_OLD_ROLE_WIDTH),
            existing_nullable=False,
        )
    else:
        with op.batch_alter_table('users', recreate='always') as batch:
            batch.alter_column(
                'role',
                existing_type=sa.String(length=_NEW_ROLE_WIDTH),
                type_=sa.String(length=_OLD_ROLE_WIDTH),
                existing_nullable=False,
            )
