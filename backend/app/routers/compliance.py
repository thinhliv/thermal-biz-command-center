"""Router Kiem toan HACCP & Phat thai Carbon ESG (Scope 1 & Scope 2).

Tuan thu tieu chuan quoc te ve an toan chuoi lanh va trach nhiem moi truong:
  - GET /api/compliance/haccp/audit: Bao cao kiem toan cac diem kiem soat toi han (CCP).
  - GET /api/compliance/esg/carbon-footprint: Phat thai Scope 1 (moi chat hao hut) & Scope 2 (kWh cong to).
  - POST /api/compliance/haccp/certificate: Phat hanh chung chi kiem toan an toan chuoi lanh.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_session
from ..security import AuditRoles, ComplianceRoles
from ..services import compliance as compliance_service
from ..services.compliance import GWP_FACTORS

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


class CertificateRequest(BaseModel):
    #: Ten lo hang la thong tin cua nguoi lap chung chi, khong duoc dien san: mot chung chi gan
    #: mac dinh "xuat khau EU/US" cho moi lo hang la chung chi sai su that.
    batch_name: str = Field(min_length=1, max_length=200)
    auditor_notes: Optional[str] = Field(default=None, max_length=1000)
    hours: int = Field(default=24, ge=1, le=720)


@router.get("/haccp/audit", dependencies=[Depends(ComplianceRoles)])
def get_haccp_audit(
    equipment_id: Optional[int] = Query(default=None, description="ID thiet bi can kiem toan"),
    hours: int = Query(default=24, ge=1, le=720, description="Khung thoi gian kiem toan (gio)"),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Kiem toan an toan thuc pham chuoi lanh HACCP."""
    return compliance_service.audit_haccp_compliance(session, equipment_id=equipment_id, hours=hours)


@router.get("/esg/carbon-footprint", dependencies=[Depends(ComplianceRoles)])
def get_esg_carbon_footprint(
    refrigerant_leak_kg: float = Query(
        ..., ge=0, description="Khoi luong moi chat lanh hao hut theo nhat ky bao tri (kg). 0 = khong hao hut."
    ),
    refrigerant_code: Optional[str] = Query(
        default=None, description="Ma moi chat lanh hao hut (R404A/R134a/R22/NH3). Bat buoc khi khoi luong > 0."
    ),
    days: int = Query(default=30, ge=1, le=365, description="So ngay tinh toan"),
    ai_saving_scenario_pct: Optional[float] = Query(
        default=None, ge=0, le=100, description="KICH BAN gia dinh % dien tiet kiem nho cat dinh phu tai"
    ),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Bao cao dau chan carbon ESG Scope 1 va Scope 2 theo GHG Protocol.

    Scope 2 tinh tu chi so cong to that; phan tram phu song du lieu nam trong `energy_coverage_pct`.
    Scope 1 can khoi luong gas hao hut do nguoi bao tri can va ghi lai - khong cam bien nao tu suy
    ra duoc con so nay, nen he thong tu choi thay vi gia dinh 4 kg R404A.
    """
    inventory = compliance_service.refrigerant_inventory(session)
    if refrigerant_code and refrigerant_code not in GWP_FACTORS:
        # Kiem tra chung cho ca hai nhanh: ma sai la loi cua nguoi goi -> 400, khong de
        # ValueError lo ra thanh 500.
        raise HTTPException(
            status_code=400,
            detail=f"Khong co he so GWP cho '{refrigerant_code}'. Cac ma hop le: {', '.join(sorted(GWP_FACTORS))}",
        )
    if refrigerant_leak_kg > 0:
        if not refrigerant_code:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Thieu refrigerant_code: moi chat lanh khac nhau co GWP khac nhau (R404A = 3922, "
                    "R134a = 1430) nen khong the tu chon. Doi xe dang dung: "
                    f"{', '.join(f'{k} ({v} thiet bi)' for k, v in sorted(inventory.items()))}"
                ),
            )
        if refrigerant_code not in inventory:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Khong thiet bi dang hoat dong nao dung '{refrigerant_code}'. "
                    f"Doi xe thuc te: {', '.join(sorted(inventory)) or '(khong co)'}"
                ),
            )
    # Hao hut = 0 thi khong co moi chat nao tham gia: giu None de bao cao noi ro
    # "KHONG_HAO_HUT" thay vi tu chon mot ma trong bang GWP roi hien ra nhu the da khai.

    return compliance_service.calculate_esg_carbon_footprint(
        session,
        days=days,
        refrigerant_leak_kg=refrigerant_leak_kg,
        refrigerant_code=refrigerant_code,
        ai_saving_scenario_pct=ai_saving_scenario_pct,
    )


@router.post("/haccp/certificate", dependencies=[Depends(AuditRoles)])
def issue_haccp_certificate(
    payload: CertificateRequest,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Phat hanh chung nhan kiem toan chuoi lanh HACCP co tem chong gia mao HMAC-SHA256.

    `status = ISSUED` nghia la van ban da duoc lap va ky, KHONG nghia la lo hang dat: ket luan nam
    o `audit_result` (COMPLIANT / NON_COMPLIANT / NOT_VERIFIABLE). Chung chi ghi nhan su that, ke
    ca khi su that do la vi pham nguong.
    """
    audit = compliance_service.audit_haccp_compliance(session, hours=payload.hours)
    return {
        "status": "ISSUED",
        "certificate_id": audit["certificate_id"],
        "batch_name": payload.batch_name,
        "auditor_notes": payload.auditor_notes,
        "audit_result": audit["overall_status"],
        "certifies_compliance": audit["overall_compliant"],
        "overall_compliance_pct": audit["overall_compliance_pct"],
        "overall_note": audit["overall_note"],
        "total_monitored_samples": audit["total_monitored_samples"],
        "total_breaches": audit["total_breaches"],
        "audited_equipment_count": audit["audited_equipment_count"],
        "signature_hash": audit["certificate_signature"],
        "signature_scheme": audit["signature_scheme"],
        "issued_at": audit["audited_at"],
        #: Khong co "valid_until": thoi han chung chi la quyet dinh cua don vi kiem toan, tu gan
        #: ngay het han o day la khong trung thuc. Chi tra ve dung khung du lieu da kiem toan.
        "audit_window_start": audit["audit_window_start"],
        "audit_window_hours": audit["audit_window_hours"],
    }

