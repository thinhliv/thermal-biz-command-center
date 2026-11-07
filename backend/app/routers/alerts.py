"""Canh bao: doc, xac nhan (acknowledge), thong ke."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import Alert, Severity, User
from ..schemas import AcknowledgeRequest, AlertPublic
from ..security import ThermalRoles
from ..services import thermal
from ..timeutil import utcnow

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertPublic])
def list_alerts(
    state: Literal["open", "cleared", "all"] = Query(default="open"),
    severity: Severity | None = Query(default=None),
    haccp_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    _: User = Depends(ThermalRoles),
) -> list[dict]:
    stmt = select(Alert)
    if state == "open":
        stmt = stmt.where(Alert.cleared_at.is_(None))
    elif state == "cleared":
        stmt = stmt.where(Alert.cleared_at.is_not(None))
    if severity is not None:
        stmt = stmt.where(Alert.severity == severity.value)
    if haccp_only:
        stmt = stmt.where(Alert.is_haccp.is_(True))
    stmt = stmt.order_by(Alert.raised_at.desc()).limit(limit)
    return [thermal.serialize_alert(a) for a in session.scalars(stmt)]


@router.get("/stats")
def alert_stats(
    session: Session = Depends(get_session), _: User = Depends(ThermalRoles)
) -> dict:
    rows = session.execute(
        select(Alert.severity, func.count(Alert.id))
        .where(Alert.cleared_at.is_(None))
        .group_by(Alert.severity)
    ).all()
    by_severity = {s.value: 0 for s in Severity}
    for severity_value, count in rows:
        by_severity[severity_value] = count

    haccp_open = session.scalar(
        select(func.count(Alert.id)).where(Alert.is_haccp.is_(True), Alert.cleared_at.is_(None))
    )
    unacknowledged = session.scalar(
        select(func.count(Alert.id)).where(
            Alert.cleared_at.is_(None), Alert.acknowledged_at.is_(None)
        )
    )
    return {
        "open_total": sum(by_severity.values()),
        "open_by_severity": by_severity,
        "haccp_open": int(haccp_open or 0),
        "unacknowledged_open": int(unacknowledged or 0),
        "as_of": utcnow().isoformat(),
    }


@router.post("/{alert_id}/acknowledge", response_model=AlertPublic)
def acknowledge(
    alert_id: int,
    payload: AcknowledgeRequest | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(ThermalRoles),
) -> dict:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Khong tim thay canh bao.")
    if alert.acknowledged_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Canh bao da duoc xac nhan luc {alert.acknowledged_at.isoformat()} "
            f"boi {alert.acknowledged_by_user.username if alert.acknowledged_by_user else '?'}.",
        )

    alert.acknowledged_at = utcnow()
    alert.acknowledged_by_id = user.id
    if payload and payload.note:
        alert.message = f"{alert.message} | Ghi chu: {payload.note}"[:500]
    session.commit()
    session.refresh(alert)
    return thermal.serialize_alert(alert)


@router.post("/{alert_id}/clear", response_model=AlertPublic)
def clear(
    alert_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(ThermalRoles),
) -> dict:
    """Dong canh bao thu cong (sau khi da xu ly xong su co)."""
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Khong tim thay canh bao.")
    if alert.cleared_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Canh bao da duoc dong truoc do.")

    if alert.acknowledged_at is None:
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by_id = user.id
    alert.cleared_at = utcnow()
    session.commit()
    session.refresh(alert)
    return thermal.serialize_alert(alert)
