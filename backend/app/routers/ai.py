"""Router AI Toi uu Nang luong Dinh (Peak-Shaving) va Bao tri Du doan (Predictive Maintenance).

Cung cap cac endpoint chuyen sau ket hop vat ly nhiet lanh va quan tri chi phi:
  - GET /api/ai/peak-shaving/schedule: Lich trinh dieu phoi 24h & uoc tinh tiet kiem dien.
  - POST /api/ai/peak-shaving/simulate: Gia lap kich ban tiet giam tai theo cong suat tuy bien.
  - GET /api/ai/predictive-maintenance/diagnostics: Chan doan rung ISO 10816-3 va suy giam COP.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_session
from ..security import AnyRole, ExecutiveOnly, ThermalRoles
from ..services import ai_energy

router = APIRouter(prefix="/api/ai", tags=["ai"])


class PeakShavingSimulateRequest(BaseModel):
    rated_power_kw: float = Field(default=120.0, gt=0, le=5000)
    base_temp_c: float = Field(default=-18.0, ge=-50, le=10)
    pre_cool_target_c: float = Field(default=-22.5, ge=-50, le=-15)
    haccp_limit_c: float = Field(default=-18.0, ge=-30, le=0)


@router.get("/peak-shaving/schedule", dependencies=[Depends(AnyRole)])
def get_peak_shaving_schedule() -> Dict[str, Any]:
    """Tra ve ke hoach dieu phoi phu tai 24h toi uu chi phi dien gio cao diem."""
    return ai_energy.calculate_peak_shaving_plan()


@router.post("/peak-shaving/simulate", dependencies=[Depends(AnyRole)])
def simulate_peak_shaving(payload: PeakShavingSimulateRequest) -> Dict[str, Any]:
    """Gia lap hieu qua cat dinh voi cong suat va nguong nhiet tuy bien."""
    return ai_energy.calculate_peak_shaving_plan(
        rated_power_kw=payload.rated_power_kw,
        base_temp_c=payload.base_temp_c,
        pre_cool_target_c=payload.pre_cool_target_c,
        haccp_limit_c=payload.haccp_limit_c,
    )


@router.get("/predictive-maintenance/diagnostics", dependencies=[Depends(AnyRole)])
def get_pdm_diagnostics(
    equipment_id: Optional[int] = Query(default=None, description="ID thiet bi can chan doan rieng"),
    session: Session = Depends(get_session),
) -> List[Dict[str, Any]]:
    """Chan doan suc khoe co khi ISO 10816-3 va suy thoai COP toan bo thiet bi."""
    return ai_energy.diagnose_predictive_maintenance(session, equipment_id=equipment_id)
