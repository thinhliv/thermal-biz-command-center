"""Dashboard tong hop. Du lieu duoc CAT theo vai tro truoc khi tra ve.

BGD thay het. Van hanh chi thay Nhiet + Canh bao. Ke toan chi thay Kinh doanh + Cong no.
Khong tra ve du lieu roi moi bao frontend an di - nhu vay van lo du lieu qua network.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import Role, User
from ..schemas import UserPublic
from ..security import AnyRole, get_current_user, scopes_for
from ..services import billing, finance, thermal
from ..timeutil import day_bounds, utcnow

router = APIRouter(prefix="/api", tags=["dashboard"])


def _build_sections(session: Session) -> dict[str, object]:
    today_start, today_end = day_bounds(utcnow())
    energy_today = billing.energy_cost_report(session, today_start, today_end)
    thermal_summary = thermal.summarize_thermal(session)

    return {
        "thermal_summary": thermal_summary,
        "alerts": thermal_summary["alerts"],
        "business": finance.business_summary(session, electricity_cost_today_vnd=energy_today["total_cost_vnd"]),
        "debts": finance.debt_summary(session),
        "energy": energy_today,
        "load_shift": billing.load_shift_analysis(
            energy_today["kwh_by_band"], energy_today["prices_vnd_per_kwh"]
        ),
    }


def _visible_keys(role: str) -> set[str]:
    scopes = set(scopes_for(role))
    keys: set[str] = set()
    if "thermal" in scopes:
        keys.add("thermal_summary")
    if "alerts" in scopes:
        keys.add("alerts")
    if "business" in scopes:
        keys.update({"business", "energy", "load_shift"})
    if "debts" in scopes:
        keys.add("debts")
    return keys


@router.get("/dashboard-summary")
def dashboard_summary(
    session: Session = Depends(get_session), user: User = Depends(AnyRole)
) -> dict:
    allowed = _visible_keys(user.role)
    sections = _build_sections(session)
    payload = {key: value for key, value in sections.items() if key in allowed}
    payload["_meta"] = {
        "role": user.role,
        "scopes": scopes_for(user.role),
        "sections": sorted(allowed & set(sections)),
        "as_of": utcnow().isoformat(),
    }
    return payload


@router.get("/dashboard-summary/stream-snapshot")
def stream_snapshot(
    session: Session = Depends(get_session), user: User = Depends(AnyRole)
) -> dict:
    """Ban nhe chi gom Nhiet + canh bao, dung cho WebSocket/UI cap nhat nhanh."""
    allowed = _visible_keys(user.role)
    sections = _build_sections(session)
    light_keys = {"thermal_summary", "alerts"} & allowed
    return {key: sections[key] for key in light_keys}
