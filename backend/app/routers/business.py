"""Kinh doanh: doanh thu, lai gop (COGS day du), chi phi dien."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import OrderStatus, ServiceOrder, User
from ..security import FinanceRoles
from ..services import billing, finance
from ..timeutil import day_bounds, utcnow

router = APIRouter(prefix="/api/business", tags=["business"])


@router.get("")
def business_summary(
    session: Session = Depends(get_session), _: User = Depends(FinanceRoles)
) -> dict:
    today_start, today_end = day_bounds(utcnow())
    energy = billing.energy_cost_report(session, today_start, today_end)
    return finance.business_summary(session, electricity_cost_today_vnd=energy["total_cost_vnd"])


@router.get("/trend")
def revenue_trend(
    days: int = Query(default=30, ge=7, le=365),
    session: Session = Depends(get_session),
    _: User = Depends(FinanceRoles),
) -> dict:
    return {"days": days, "series": finance.revenue_series(session, days=days)}


@router.get("/orders")
def list_orders(
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
    _: User = Depends(FinanceRoles),
) -> dict:
    orders = list(
        session.scalars(
            select(ServiceOrder)
            .where(ServiceOrder.status != OrderStatus.CANCELLED.value)
            .order_by(ServiceOrder.started_at.desc())
            .limit(limit)
        )
    )
    return {
        "count": len(orders),
        "items": [
            {
                "order_code": o.code,
                "customer": o.customer.name if o.customer else "",
                "service": o.service_type,
                "volume_tons": o.volume_tons,
                "revenue_vnd": o.revenue_vnd,
                "cogs_vnd": o.total_cogs_vnd,
                "cogs_breakdown": {
                    "electricity_vnd": o.electricity_cost_vnd,
                    "refrigerant_vnd": o.refrigerant_cost_vnd,
                    "labor_vnd": o.labor_cost_vnd,
                    "maintenance_vnd": o.maintenance_cost_vnd,
                    "overhead_vnd": o.overhead_cost_vnd,
                },
                "gross_profit_vnd": o.gross_profit_vnd,
                "margin_pct": o.gross_margin_pct,
                "started_at": o.started_at.isoformat(),
                "ended_at": o.ended_at.isoformat() if o.ended_at else None,
                "status": o.status,
            }
            for o in orders
        ],
    }


@router.get("/tariff")
def current_tariff(
    session: Session = Depends(get_session), _: User = Depends(FinanceRoles)
) -> dict:
    """Bieu gia EVN TOU dang hieu luc - nguon cua moi con so tien dien."""
    bands = billing.active_bands(session, utcnow())
    return {
        "bands": [
            {
                "code": b.code,
                "name_vn": b.name_vn,
                "start_minute": b.start_minute,
                "end_minute": b.end_minute,
                "window": f"{b.start_minute // 60:02d}:{b.start_minute % 60:02d}-"
                f"{b.end_minute // 60:02d}:{b.end_minute % 60:02d}",
                "days": b.days,
                "price_vnd_per_kwh": b.price_vnd_per_kwh,
                "effective_from": b.effective_from.isoformat(),
            }
            for b in bands
        ],
        "prices_vnd_per_kwh": billing.band_prices(bands),
        "note": "Gia ban le dien theo Quyet dinh cua Bo Cong Thuong. Cap nhat bang tariff_bands "
        "khi co quyet dinh moi - khong sua trong code.",
    }
