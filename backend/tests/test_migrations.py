"""Migration phai sinh ra DUNG schema ma models khai bao.

Dev chay `create_all()`, prod chay `alembic upgrade head`. Hai duong ma lech nhau
thi dev van xanh con prod deploy ra schema sai - loai bug chi lo ra luc rollout.
Test nay chan ngay trong vong CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app import models  # noqa: F401  (dang ky metadata vao Base.metadata)
from app.config import get_settings
from app.database import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent


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


@pytest.fixture()
def alembic_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, str]]:
    """Chay `alembic upgrade head` len mot SQLite file tam.

    env.py doc URL tu settings (khong tu alembic.ini) nen phai doi settings,
    set_main_option("sqlalchemy.url") o day se bi env.py ghi de.
    """
    url = f"sqlite:///{(tmp_path / 'alembic.db').as_posix()}"
    monkeypatch.setattr(get_settings(), "alembic_database_url", url)

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")
    return _schema(url)


@pytest.fixture()
def model_schema(tmp_path: Path) -> dict[str, dict[str, str]]:
    url = f"sqlite:///{(tmp_path / 'create_all.db').as_posix()}"
    engine = create_engine(url)
    try:
        Base.metadata.create_all(bind=engine)
    finally:
        engine.dispose()
    return _schema(url)


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
