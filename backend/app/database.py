"""SQLAlchemy engine/session.

Dev: SQLite (khong can cai dat). Prod: Postgres - chi can doi DATABASE_URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str, echo: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        # ":memory:" phai dung StaticPool, neu khong moi ket noi thay mot DB rong khac
        if ":memory:" in url or "mode=memory" in url:
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    return kwargs


settings = get_settings()
engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url, settings.db_echo))

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        """SQLite TAT foreign key mac dinh - phai bat, neu khong FK chi la trang tri."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: mot session cho moi request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_all() -> None:
    """Chi dung cho test/demo. Prod dung Alembic: `alembic upgrade head`."""
    from . import models  # noqa: F401  (dang ky metadata truoc khi create)

    Base.metadata.create_all(bind=engine)


def dispose() -> None:
    engine.dispose()
