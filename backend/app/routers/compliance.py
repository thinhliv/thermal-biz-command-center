"""Router Kiem toan HACCP & Phat thai Carbon ESG (Scope 1 & Scope 2).

Tuan thu tieu chuan quoc te ve an toan chuoi lanh va trach nhiem moi truong:
  - GET /api/compliance/haccp/audit: Bao cao kiem toan nhiet do kho thuy hai san (<= -18C).
  - GET /api/compliance/esg/carbon-footprint: Tinh toan phat thai Scope 1 (R404A) & Scope 2 (EVN).
  - POST /api/compliance/haccp/certificate: Phat hanh chung chi kiem toan an toan chuoi lanh.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_session
from ..security import AnyRole, AuditRoles, ExecutiveOnly
from ..services import compliance as compliance_service

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


class CertificateRequest(BaseModel):
    batch_name: str = Field(default="Lô hàng thủy sản đông lạnh xuất khẩu EU/US")
    auditor_notes: Optional[str] = Field(default="Đạt tiêu chuẩn HACCP Codex Alimentarius")
    hours: int = Field(default=24, ge=1, le=720)


@router.get("/haccp/audit", dependencies=[Depends(AnyRole)])
def get_haccp_audit(
    equipment_id: Optional[int] = Query(default=None, description="ID thiet bi can kiem toan"),
    hours: int = Query(default=24, ge=1, le=720, description="Khung thoi gian kiem toan (gio)"),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Kiem toan an toan thuc pham chuoi lanh HACCP."""
    return compliance_service.audit_haccp_compliance(session, equipment_id=equipment_id, hours=hours)


@router.get("/esg/carbon-footprint", dependencies=[Depends(AnyRole)])
def get_esg_carbon_footprint(
    days: int = Query(default=30, ge=1, le=365, description="So ngay tinh toan"),
    refrigerant_leak_kg: float = Query(default=4.0, ge=0, description="Khoi luong R404A hao hut (kg)"),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Bao cao dau chan carbon ESG Scope 1 va Scope 2 theo GHG Protocol."""
    return compliance_service.calculate_esg_carbon_footprint(
        session, days=days, refrigerant_leak_kg=refrigerant_leak_kg
    )


@router.post("/haccp/certificate", dependencies=[Depends(AuditRoles)])
def issue_haccp_certificate(
    payload: CertificateRequest,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Phat hanh chung nhan kiem toan chuoi lanh HACCP dien tu co chu ky so."""
    audit = compliance_service.audit_haccp_compliance(session, hours=payload.hours)
    return {
        "status": "ISSUED",
        "certificate_id": audit["certificate_id"],
        "batch_name": payload.batch_name,
        "auditor_notes": payload.auditor_notes,
        "overall_compliant": audit["overall_compliant"],
        "overall_compliance_pct": audit["overall_compliance_pct"],
        "total_monitored_samples": audit["total_monitored_samples"],
        "total_breaches": audit["total_breaches"],
        "signature_hash": audit["certificate_signature"],
        "issued_at": audit["audited_at"],
        "valid_until": audit["audited_at"],
    }
