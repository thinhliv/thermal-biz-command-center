"""Nhiet lanh: telemetry, chuoi thoi gian, chi phi dien, nguong canh bao."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import AlarmRule, Equipment, User
from ..schemas import AlarmRuleIn, AlarmRulePublic, TelemetryRow, ThermalSummary
from ..security import ExecutiveOnly, ThermalRoles
from ..services import billing, thermal
from ..timeutil import day_bounds, utcnow

router = APIRouter(prefix="/api/thermal", tags=["thermal"])


def _equipment_or_404(session: Session, code: str) -> Equipment:
    equipment = session.scalars(select(Equipment).where(Equipment.code == code.strip())).first()
    if equipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Khong tim thay thiet bi '{code}'.")
    return equipment


def _row(session: Session, equipment: Equipment) -> dict:
    sample = thermal.latest_sample(session, equipment.id)
    if sample is None:
        return {
            "equipment_code": equipment.code,
            "equipment_name": equipment.name,
            "kind": equipment.kind,
            "status": "NO_DATA",
            "is_refrigeration": equipment.is_refrigeration,
            "is_combustion": equipment.is_combustion,
        }
    health = thermal.assess_health(equipment, sample)
    return {
        "equipment_code": equipment.code,
        "equipment_name": equipment.name,
        "kind": equipment.kind,
        "status": sample.status or "UNKNOWN",
        "temperature_c": sample.temperature_c,
        "pressure_bar": sample.pressure_bar,
        "power_kw": sample.power_kw,
        "cooling_capacity_kw": sample.cooling_capacity_kw,
        # COP chi co nghia voi thiet bi lanh; lo hoi tra ve None (khong con 0.89 nham la COP)
        "cop": sample.cop if equipment.is_refrigeration else None,
        "design_cop": equipment.design_cop if equipment.is_refrigeration else None,
        "cop_gap_pct": health.cop_gap_pct,
        "efficiency_pct": sample.efficiency_pct if equipment.is_combustion else None,
        "design_efficiency_pct": equipment.design_efficiency_pct if equipment.is_combustion else None,
        "vibration_mm_s": sample.vibration_mm_s,
        "vibration_critical": health.vibration_critical,
        "haccp_limit_c": equipment.haccp_limit_c,
        "haccp_breach": health.haccp_breach,
        "is_refrigeration": equipment.is_refrigeration,
        "is_combustion": equipment.is_combustion,
        "ts": sample.ts.isoformat() if sample.ts else None,
    }


@router.get("/summary", response_model=ThermalSummary)
def summary(session: Session = Depends(get_session), _: User = Depends(ThermalRoles)) -> dict:
    return thermal.summarize_thermal(session)


@router.get("", response_model=list[TelemetryRow])
def list_latest(session: Session = Depends(get_session), _: User = Depends(ThermalRoles)) -> list[dict]:
    return [_row(session, e) for e in thermal.active_equipment(session)]


@router.get("/energy")
def energy_report(
    hours: int = Query(default=24, ge=1, le=24 * 90),
    today_only: bool = Query(default=False),
    session: Session = Depends(get_session),
    _: User = Depends(ThermalRoles),
) -> dict:
    """Chi phi dien noi bo cua nha may, tinh that tu telemetry x bieu gia EVN TOU."""
    if today_only:
        start, end = day_bounds(utcnow())
    else:
        end = utcnow()
        start = end - timedelta(hours=hours)
    return billing.energy_cost_report(session, start, end)


@router.get("/rules", response_model=list[AlarmRulePublic])
def list_rules(session: Session = Depends(get_session), _: User = Depends(ThermalRoles)) -> list[AlarmRule]:
    return list(session.scalars(select(AlarmRule).order_by(AlarmRule.id)))


@router.post("/rules", response_model=AlarmRulePublic, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: AlarmRuleIn,
    session: Session = Depends(get_session),
    _: User = Depends(ExecutiveOnly),
) -> AlarmRule:
    equipment_id = None
    if payload.equipment_code:
        equipment_id = _equipment_or_404(session, payload.equipment_code).id
    rule = AlarmRule(
        equipment_id=equipment_id,
        applies_to_kind=payload.applies_to_kind,
        metric=payload.metric.value,
        comparator=payload.comparator.value,
        threshold=payload.threshold,
        duration_minutes=payload.duration_minutes,
        severity=payload.severity.value,
        message_template=payload.message_template,
        is_haccp=payload.is_haccp,
        enabled=payload.enabled,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


@router.get("/equipment")
def list_equipment(
    session: Session = Depends(get_session), _: User = Depends(ThermalRoles)
) -> list[dict]:
    """Danh muc thiet bi + thong so thiet ke (de hien thi nguon COP / eta)."""
    return [
        {
            "code": e.code,
            "name": e.name,
            "kind": e.kind,
            "location": e.location,
            "refrigerant": e.refrigerant,
            "rated_power_kw": e.rated_power_kw,
            "setpoint_c": e.setpoint_c,
            "haccp_limit_c": e.haccp_limit_c,
            "design_cop": e.design_cop,
            "design_efficiency_pct": e.design_efficiency_pct,
            "tenant_code": e.tenant_code,
            "meter_entity_id": e.meter_entity_id,
            "is_active": e.is_active,
            "is_refrigeration": e.is_refrigeration,
            "is_combustion": e.is_combustion,
        }
        for e in thermal.active_equipment(session)
    ]


@router.get("/{code}/series")
def series(
    code: str,
    hours: int = Query(default=24, ge=1, le=24 * 90),
    session: Session = Depends(get_session),
    _: User = Depends(ThermalRoles),
) -> dict:
    equipment = _equipment_or_404(session, code)
    samples = thermal.telemetry_series(session, equipment.id, hours=hours)
    return {
        "equipment_code": equipment.code,
        "equipment_name": equipment.name,
        "kind": equipment.kind,
        "is_refrigeration": equipment.is_refrigeration,
        "is_combustion": equipment.is_combustion,
        "setpoint_c": equipment.setpoint_c,
        "haccp_limit_c": equipment.haccp_limit_c,
        "design_cop": equipment.design_cop,
        "design_efficiency_pct": equipment.design_efficiency_pct,
        "points": [
            {
                "ts": s.ts.isoformat(),
                "temperature_c": s.temperature_c,
                "pressure_bar": s.pressure_bar,
                "power_kw": s.power_kw,
                "cooling_capacity_kw": s.cooling_capacity_kw,
                "cop": s.cop,
                "efficiency_pct": s.efficiency_pct,
                "vibration_mm_s": s.vibration_mm_s,
                "energy_kwh_cumulative": s.energy_kwh_cumulative,
                "status": s.status,
            }
            for s in samples
        ],
    }
