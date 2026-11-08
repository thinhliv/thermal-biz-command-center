"""Moc thoi gian UTC.

Luu datetime KHONG kem timezone va luon la UTC. Ly do: SQLite khong giu tzinfo,
neu de tz-aware thi doc ra tu SQLite se la naive -> so sanh voi tz-aware se TypeError.
Nhat quan naive-UTC tren ca SQLite lan Postgres.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utctoday() -> date:
    return utcnow().date()


def month_bounds(moment: datetime | None = None) -> tuple[datetime, datetime]:
    """(dau thang, dau thang ke tiep) cua thang chua `moment`."""
    moment = moment or utcnow()
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def day_bounds(moment: datetime | None = None) -> tuple[datetime, datetime]:
    moment = moment or utcnow()
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)
