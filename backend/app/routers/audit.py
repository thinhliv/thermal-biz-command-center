"""Router cho Nhat ky kiem toan bat bien (Immutable Audit Trail).

Cho phep cap lanh dao va nguoi kiem soat chat luong (bundle `AuditRoles`: BGD, L1, L2,
L3, L6_HACCP_AUDITOR, L8) truy van nhat ky van hanh va xac minh tinh toan ven chuoi
chu ky HMAC.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import AuditLog
from ..security import AuditRoles
from ..services.audit import verify_audit_chain

router = APIRouter(prefix="/api/audit", tags=["Audit Trail"])


class AuditLogResponse(BaseModel):
    id: int
    timestamp: str
    username: str
    user_role: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    details: Dict[str, Any]
    previous_hash: str
    signature_hash: str


@router.get("/logs", dependencies=[Depends(AuditRoles)])
def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)

    # COUNT(*) tren DB, khong keo het id ve roi dem bang len(): nhat ky kiem toan la bang
    # lon nhat he thong va chi lon dan, mot lan mo trang khong duoc tieu thu bo nho
    # ty le thuan voi so nam van hanh.
    total = int(session.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0)

    records = list(
        session.scalars(
            select(AuditLog).where(*conditions).order_by(desc(AuditLog.id)).offset(offset).limit(limit)
        )
    )

    items = [
        AuditLogResponse(
            id=r.id,
            timestamp=r.timestamp.isoformat(),
            username=r.username,
            user_role=r.user_role,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            ip_address=r.ip_address,
            details=r.details or {},
            previous_hash=r.previous_hash,
            signature_hash=r.signature_hash,
        ).model_dump()
        for r in records
    ]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": items,
    }


@router.get("/verify", dependencies=[Depends(AuditRoles)])
def verify_integrity(session: Session = Depends(get_session)) -> Dict[str, Any]:
    """Kiem tra toan bo chuoi ma hoa SHA-256 de dam bao khong ai can thiep vao DB."""
    return verify_audit_chain(session)
