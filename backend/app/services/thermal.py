"""Ky thuat nhiet lanh: COP, nguong canh bao, HACCP, ISO 10816.

Diem nghiep vu quan trong:
- COP = Q_o / N_e (cong suat lanh / cong suat dien). Chi ap dung cho thiet bi lanh.
- Lo hoi dung HIEU SUAT eta (%), khong dung COP. Hai dai luong nay khong duoc lan lon.
- COP < nguong keo dai => thieu gas lanh hoac dan nong ban.
- Rung > 4.5 mm/s => ranh gioi vung C/D theo ISO 10816.
- Chuoi lanh hai san phai <= -18 C (HACCP).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Alert,
    AlarmRule,
    Equipment,
    TelemetrySample,
)
from ..timeutil import utcnow

#: ISO 10816-3: > 4.5 mm/s la ranh gioi vung C/D (khong dat yeu cau van hanh)
VIBRATION_ISO10816_LIMIT_MM_S = 4.5

#: Hai san bao quan dong: nhiet do tam toi da theo HACCP
HACCP_SEAFOOD_LIMIT_C = -18.0


def compute_cop(cooling_capacity_kw: float | None, power_kw: float | None) -> float | None:
    """COP = Q_o / N_e. Tra ve None khi thieu du lieu hoac N_e <= 0 (may dung)."""
    if cooling_capacity_kw is None or power_kw is None or power_kw <= 0:
        return None
    return round(cooling_capacity_kw / power_kw, 3)


@dataclass(frozen=True)
class EquipmentHealth:
    """Ket luan suc khoe thiet bi tu mau telemetry moi nhat."""

    code: str
    status: str
    cop: float | None
    efficiency_pct: float | None
    cop_gap_pct: float | None
    is_refrigeration: bool
    is_combustion: bool
    haccp_breach: bool
    vibration_critical: bool


def assess_health(equipment: Equipment, sample: TelemetrySample) -> EquipmentHealth:
    haccp_breach = (
        equipment.haccp_limit_c is not None
        and sample.temperature_c is not None
        and sample.temperature_c > equipment.haccp_limit_c
    )
    cop_gap_pct = None
    if equipment.is_refrigeration and sample.cop is not None and equipment.design_cop:
        cop_gap_pct = round((sample.cop - equipment.design_cop) / equipment.design_cop * 100, 2)

    return EquipmentHealth(
        code=equipment.code,
        status=sample.status or "UNKNOWN",
        cop=sample.cop,
        efficiency_pct=sample.efficiency_pct,
        cop_gap_pct=cop_gap_pct,
        is_refrigeration=equipment.is_refrigeration,
        is_combustion=equipment.is_combustion,
        haccp_breach=haccp_breach,
        vibration_critical=(sample.vibration_mm_s or 0) > VIBRATION_ISO10816_LIMIT_MM_S,
    )


# --------------------------------------------------------------------------- #
# Co che canh bao
# --------------------------------------------------------------------------- #
def rules_for(session: Session, equipment: Equipment, enabled_only: bool = True) -> list[AlarmRule]:
    stmt = select(AlarmRule).where(
        ((AlarmRule.equipment_id == equipment.id) | (AlarmRule.equipment_id.is_(None)))
    )
    if enabled_only:
        stmt = stmt.where(AlarmRule.enabled.is_(True))
    return [r for r in session.scalars(stmt) if r.matches_kind(equipment)]


def _breached_throughout(session: Session, rule: AlarmRule, equipment_id: int, sample: TelemetrySample) -> bool:
    """Kiem tra vi pham co keo dai suot `duration_minutes` hay khong (chong nhieu nhay)."""
    if rule.duration_minutes <= 0:
        return True

    window_start = sample.ts - timedelta(minutes=rule.duration_minutes)
    stmt = (
        select(TelemetrySample)
        .where(
            TelemetrySample.equipment_id == equipment_id,
            TelemetrySample.ts >= window_start,
            TelemetrySample.ts <= sample.ts,
        )
        .order_by(TelemetrySample.ts)
    )
    window = list(session.scalars(stmt))
    if len(window) < 2:
        # Chua du du lieu de ket luan "keo dai" -> khong bao dong sai
        return False
    return all(rule.is_breached(getattr(s, rule.metric, None)) for s in window)


def _open_alert(session: Session, rule_id: int, equipment_id: int) -> Alert | None:
    stmt = select(Alert).where(
        Alert.rule_id == rule_id,
        Alert.equipment_id == equipment_id,
        Alert.cleared_at.is_(None),
    )
    return session.scalars(stmt).first()


def evaluate_sample(session: Session, equipment: Equipment, sample: TelemetrySample) -> list[Alert]:
    """Cham diem mot mau telemetry theo cac rule. Tra ve danh sach Alert MOI duoc tao.

    Co day du vong doi: vi pham -> tao Alert; het vi pham -> dong Alert (set cleared_at).
    Khong tao Alert trung khi mot canh bao cua cung rule van con dang mo.
    Mau thieu du lieu (value None) KHONG duoc dong canh bao - day la thiet bi hong cam bien,
    khong phai la da het su co.
    """
    created: list[Alert] = []

    for rule in rules_for(session, equipment):
        value = getattr(sample, rule.metric, None)
        if value is None:
            continue

        existing = _open_alert(session, rule.id, equipment.id)

        if rule.is_breached(value):
            if existing is not None:
                continue
            if not _breached_throughout(session, rule, equipment.id, sample):
                continue
            alert = Alert(
                rule_id=rule.id,
                equipment_id=equipment.id,
                severity=rule.severity,
                metric=rule.metric,
                observed_value=value,
                threshold=rule.threshold,
                message=rule.render_message(equipment, value) or f"{equipment.name}: {rule.metric} = {value}",
                is_haccp=rule.is_haccp,
                raised_at=sample.ts or utcnow(),
            )
            session.add(alert)
            created.append(alert)
        elif existing is not None:
            existing.cleared_at = sample.ts or utcnow()

    session.flush()
    return created


# --------------------------------------------------------------------------- #
# Truy van tong hop
# --------------------------------------------------------------------------- #
def latest_sample(session: Session, equipment_id: int) -> TelemetrySample | None:
    stmt = (
        select(TelemetrySample)
        .where(TelemetrySample.equipment_id == equipment_id)
        .order_by(TelemetrySample.ts.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def active_equipment(session: Session) -> list[Equipment]:
    stmt = select(Equipment).where(Equipment.is_active.is_(True)).order_by(Equipment.code)
    return list(session.scalars(stmt))


def open_alerts(session: Session, limit: int = 50) -> list[Alert]:
    stmt = (
        select(Alert)
        .where(Alert.cleared_at.is_(None))
        .order_by(Alert.raised_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def serialize_alert(alert: Alert) -> dict:
    """Dict JSON-safe: thoi gian dang ISO string.

    WebSocket gui payload bang json.dumps (khong co jsonable_encoder cua FastAPI)
    nen datetime o day se lam crash ca socket. REST tra ve y het.
    """
    return {
        "id": alert.id,
        "severity": alert.severity,
        "message": alert.message,
        "metric": alert.metric,
        "observed_value": alert.observed_value,
        "threshold": alert.threshold,
        "is_haccp": alert.is_haccp,
        "equipment_code": alert.equipment.code if alert.equipment else None,
        "raised_at": alert.raised_at.isoformat() if alert.raised_at else None,
        "cleared_at": alert.cleared_at.isoformat() if alert.cleared_at else None,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "acknowledged_by": alert.acknowledged_by_user.username if alert.acknowledged_by_user else None,
    }


def telemetry_series(
    session: Session, equipment_id: int, hours: int = 24, limit: int = 2000
) -> list[TelemetrySample]:
    since = utcnow() - timedelta(hours=hours)
    # Lay `limit` mau MOI NHAT (desc) roi dao lai -> tra ve tang dan theo thoi gian cho bieu do.
    stmt = (
        select(TelemetrySample)
        .where(TelemetrySample.equipment_id == equipment_id, TelemetrySample.ts >= since)
        .order_by(TelemetrySample.ts.desc())
        .limit(limit)
    )
    return session.scalars(stmt).all()[::-1]


def summarize_thermal(session: Session) -> dict:
    """Tong hop Nhiet cho dashboard: chi tinh COP tren thiet bi lanh, khong lan voi lo hoi."""
    equipment_list = active_equipment(session)

    total_power_kw = 0.0
    refrigeration_cops: list[float] = []
    boiler_efficiencies: list[float] = []
    running = warning = fault = 0
    rows: list[dict] = []

    for equipment in equipment_list:
        sample = latest_sample(session, equipment.id)
        if sample is None:
            rows.append(
                {
                    "equipment_code": equipment.code,
                    "equipment_name": equipment.name,
                    "kind": equipment.kind,
                    "status": "NO_DATA",
                    "temperature_c": None,
                    "pressure_bar": None,
                    "power_kw": None,
                    "cop": None,
                    "efficiency_pct": None,
                    "vibration_mm_s": None,
                    "is_refrigeration": equipment.is_refrigeration,
                    "is_combustion": equipment.is_combustion,
                    "haccp_breach": False,
                }
            )
            continue

        health = assess_health(equipment, sample)
        if sample.power_kw:
            total_power_kw += sample.power_kw
        if equipment.is_refrigeration and sample.cop is not None:
            refrigeration_cops.append(sample.cop)
        if equipment.is_combustion and sample.efficiency_pct is not None:
            boiler_efficiencies.append(sample.efficiency_pct)

        status_value = sample.status or "UNKNOWN"
        if status_value == "RUNNING":
            running += 1
        if health.haccp_breach or health.vibration_critical:
            warning += 1
        if status_value == "FAULT":
            fault += 1

        rows.append(
            {
                "equipment_code": equipment.code,
                "equipment_name": equipment.name,
                "kind": equipment.kind,
                "status": status_value,
                "temperature_c": sample.temperature_c,
                "pressure_bar": sample.pressure_bar,
                "power_kw": sample.power_kw,
                "cooling_capacity_kw": sample.cooling_capacity_kw,
                # COP chi co nghia voi thiet bi lanh -> NULL voi lo hoi, khong hien 0.89 nua
                "cop": sample.cop if equipment.is_refrigeration else None,
                "design_cop": equipment.design_cop,
                "cop_gap_pct": health.cop_gap_pct,
                "efficiency_pct": sample.efficiency_pct if equipment.is_combustion else None,
                "design_efficiency_pct": equipment.design_efficiency_pct,
                "vibration_mm_s": sample.vibration_mm_s,
                "vibration_critical": health.vibration_critical,
                "haccp_limit_c": equipment.haccp_limit_c,
                "haccp_breach": health.haccp_breach,
                "is_refrigeration": equipment.is_refrigeration,
                "is_combustion": equipment.is_combustion,
                "ts": sample.ts.isoformat() if sample.ts else None,
            }
        )

    alert_rows = [serialize_alert(alert) for alert in open_alerts(session, limit=30)]

    return {
        "total_power_kw": round(total_power_kw, 2),
        # Tach ro 2 chi so: COP binh quan (lanh) va hieu suat binh quan (lo hoi)
        "avg_cop": round(sum(refrigeration_cops) / len(refrigeration_cops), 2) if refrigeration_cops else None,
        "avg_boiler_efficiency_pct": (
            round(sum(boiler_efficiencies) / len(boiler_efficiencies), 2) if boiler_efficiencies else None
        ),
        "total_units": len(equipment_list),
        "running": running,
        "warning": warning,
        "fault": fault,
        "telemetry": rows,
        "alerts": alert_rows,
        "vibration_limit_mm_s": VIBRATION_ISO10816_LIMIT_MM_S,
        "haccp_seafood_limit_c": HACCP_SEAFOOD_LIMIT_C,
    }
