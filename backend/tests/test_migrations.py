"""Migration phai sinh ra DUNG schema ma models khai bao.

Dev chay `create_all()`, prod chay `alembic upgrade head`. Hai duong ma lech nhau
thi dev van xanh con prod deploy ra schema sai - loai bug chi lo ra luc rollout.
Test nay chan ngay trong vong CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, create_engine, inspect, text

from app import models  # noqa: F401  (dang ky metadata vao Base.metadata)
from app.config import get_settings
from app.database import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent

_IN_CHECK = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+IN\s*\(", re.IGNORECASE)
_SQL_LITERAL = re.compile(r"'((?:[^']|'')*)'")


def _schema(url: str) -> dict[str, dict[str, str]]:
    """{bang: {cot: kieu}} phan chieu tu DB. Dung inspector, khong noi chuoi vao SQL."""
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        return {
            table: {col["name"]: str(col["type"]) for col in inspector.get_columns(table)}
            for table in sorted(inspector.get_table_names())
        }
    finally:
        engine.dispose()


def _checks(url: str) -> dict[str, set[tuple[str, str]]]:
    """{bang: {(ten_constraint, sql)}} - lop drift ma _schema() khong nhin thay.

    So cot va kieu cot van khop ma CHECK constraint khac nhau thi van la drift:
    `users.ck_users_role` tung liet ke 3 vai trong migration trong khi model sinh 13
    vai tu enum. SQLite dev lay constraint tu model nen van xanh, Postgres prod lay
    tu migration nen chan moi user L1..L10 - va `alembic upgrade head` khong bao loi
    vi tao ra mot constraint SAI thi van thanh cong.
    """
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        found: dict[str, set[tuple[str, str]]] = {}
        for table in sorted(inspector.get_table_names()):
            entries = {
                (ck.get("name") or "", " ".join(str(ck.get("sqltext") or "").split()))
                for ck in inspector.get_check_constraints(table)
            }
            if entries:
                found[table] = entries
        return found
    finally:
        engine.dispose()


@pytest.fixture()
def alembic_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Chay `alembic upgrade head` len mot SQLite file tam, tra ve URL cua no.

    env.py doc URL tu settings (khong tu alembic.ini) nen phai doi settings,
    set_main_option("sqlalchemy.url") o day se bi env.py ghi de.
    """
    url = f"sqlite:///{(tmp_path / 'alembic.db').as_posix()}"
    monkeypatch.setattr(get_settings(), "alembic_database_url", url)

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")
    return url


@pytest.fixture()
def model_url(tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'create_all.db').as_posix()}"
    engine = create_engine(url)
    try:
        Base.metadata.create_all(bind=engine)
    finally:
        engine.dispose()
    return url


@pytest.fixture()
def alembic_schema(alembic_url: str) -> dict[str, dict[str, str]]:
    return _schema(alembic_url)


@pytest.fixture()
def model_schema(model_url: str) -> dict[str, dict[str, str]]:
    return _schema(model_url)


@pytest.fixture()
def alembic_checks(alembic_url: str) -> dict[str, set[tuple[str, str]]]:
    return _checks(alembic_url)


@pytest.fixture()
def model_checks(model_url: str) -> dict[str, set[tuple[str, str]]]:
    return _checks(model_url)


def test_migration_tao_du_moi_bang_cua_models(alembic_schema, model_schema):
    assert set(alembic_schema) - {"alembic_version"} == set(model_schema)


def test_migration_tao_dung_tung_cot(alembic_schema, model_schema):
    """So tung cot mot: thieu/thua cot hoac sai kieu deu la drift nghiem trong."""
    drifted: dict[str, object] = {}
    for table, columns in model_schema.items():
        migrated = alembic_schema.get(table, {})
        missing = set(columns) - set(migrated)
        extra = set(migrated) - set(columns)
        wrong_type = {
            name: (migrated[name], expected)
            for name, expected in columns.items()
            if name in migrated and migrated[name] != expected
        }
        if missing or extra or wrong_type:
            drifted[table] = {"thieu": sorted(missing), "thua": sorted(extra), "sai_kieu": wrong_type}

    assert not drifted, f"Schema migration lech models: {drifted}"


def test_migration_danh_dau_phien_ban_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """alembic_version phai duoc stamp, neu khong lan upgrade sau se chay lai migration dau."""
    url = f"sqlite:///{(tmp_path / 'stamped.db').as_posix()}"
    monkeypatch.setattr(get_settings(), "alembic_database_url", url)

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()

    assert version == ScriptDirectory.from_config(config).get_current_head()


def test_migration_tao_dung_check_constraint(alembic_checks, model_checks):
    """CHECK constraint cung phai khop, khong chi cot.

    Day la loai drift `test_migration_tao_dung_tung_cot` khong bat duoc: ten cot va
    kieu cot giong het nhau, chi co noi dung constraint la khac.
    """
    drifted = {
        table: {"migration": sorted(alembic_checks.get(table, set())), "models": sorted(expected)}
        for table, expected in model_checks.items()
        if alembic_checks.get(table) != expected
    }
    assert not drifted, f"CHECK constraint migration lech models: {drifted}"


def test_moi_vai_trong_enum_deu_duoc_phep_luu_vao_db(alembic_url):
    """Hoi sinh loi that: them vai vao enum ma quen migration thi prod chan chinh vai do.

    `ck_users_role` tung dong cung ('BGD','VANHANH','KETOAN') trong khi enum co 13 vai.
    Dev dung create_all() (lay constraint tu model) nen test van xanh, con Postgres
    prod dung alembic nen INSERT user L1..L10 vi pham CHECK - va `alembic upgrade head`
    khong bao loi vi tao ra mot constraint SAI van la mot buoc upgrade thanh cong.
    """
    engine = create_engine(alembic_url)
    try:
        with engine.begin() as connection:
            for index, role in enumerate(models.Role):
                connection.execute(
                    text(
                        "INSERT INTO users (username, password_hash, role, full_name, is_active, created_at) "
                        "VALUES (:u, 'hash', :r, :n, 1, '2026-01-01 00:00:00')"
                    ),
                    {"u": f"role_probe_{index}", "r": role.value, "n": role.value},
                )
    finally:
        engine.dispose()


def _enum_backed_in_checks() -> list[tuple[str, str, int | None, str]]:
    """[(bang, cot, do_rong_khai_bao, gia_tri_dai_nhat_ma_CHECK_cho_phep)].

    Doc truc tiep tu models: cot co `IN (...)` la cot ma tap gia tri hop le da bi
    khoa cung, nen do rong khai bao phai chua duoc gia tri dai nhat trong do.
    """
    probes: list[tuple[str, str, int | None, str]] = []
    for table in Base.metadata.sorted_tables:
        widths = {col.name: getattr(col.type, "length", None) for col in table.columns}
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue
            sqltext = getattr(constraint, "sqltext", None)
            sql = str(sqltext) if sqltext is not None else ""
            match = _IN_CHECK.match(sql)
            if not match:
                continue
            column = match.group(1)
            if column not in widths:
                continue
            values = [raw.replace("''", "'") for raw in _SQL_LITERAL.findall(sql)]
            if values:
                probes.append((table.name, column, widths[column], max(values, key=len)))
    return probes


def test_do_rong_cot_chua_du_moi_gia_tri_ma_check_constraint_cho_phep():
    """Cot phai chua duoc chinh nhung gia tri ma CHECK constraint cho phep.

    Loi that da xay ra: `users.role` khai bao VARCHAR(16) trong khi enum `Role` co
    6/13 vai dai hon (dai nhat 23 ky tu). SQLite khong kiem tra do dai VARCHAR nen
    `test_moi_vai_trong_enum_deu_duoc_phep_luu_vao_db` van xanh, con Postgres chan
    INSERT bang "value too long for type character varying(16)" - tuc la nhung vai
    do khong the ton tai tren prod, va loi chi lo ra sau khi da rollout.

    Cac test drift o tren KHONG bat duoc loai nay: chung so sanh migration voi
    models, ma ca hai cung khai bao VARCHAR(16) thi van la "khop". Vi the test nay
    doc models doc lap - them mot gia tri enum dai hon do rong cot la do ngay trong
    CI, khong doi den luc nguoi dung dau tien mang vai do dang nhap.
    """
    probes = _enum_backed_in_checks()

    # Chan test khoi xanh rong: neu regex khong con khop duoc constraint nao thi
    # assert duoi day luon dung va khong con bao ve gi ca.
    assert probes, "Khong doc duoc cot IN-check nao tu models - test nay da thanh vo nghia."

    overflow = [
        f"{table}.{column}: khai bao VARCHAR({width}) nhung CHECK cho phep {longest!r} ({len(longest)} ky tu)"
        for table, column, width, longest in probes
        if width is not None and len(longest) > width
    ]
    assert not overflow, (
        "Do rong cot khong chua het gia tri hop le (SQLite bo qua nen dev xanh, "
        "Postgres chan INSERT): " + "; ".join(overflow)
    )


def test_khong_con_drift_giua_migration_va_models(alembic_url):
    """`alembic check`: autogenerate phai khong de xuat them buoc nao.

    Bat duoc ca nhung lech ma so sanh cot/constraint bang chuoi bo sot (vi du kieu
    cot FK), va chan viec sua models.py ma quen viet migration.
    """
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

    try:
        command.check(config)
    except Exception as exc:  # alembic check nem khi phat hien drift
        pytest.fail(f"alembic check thay drift giua models va migrations: {exc}")
