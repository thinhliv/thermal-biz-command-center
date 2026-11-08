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
from ..security import AiRoles
from ..services import ai_energy

router = APIRouter(prefix="/api/ai", tags=["ai"])


class PeakShavingSimulateRequest(BaseModel):
    #: KHONG co haccp_limit_c: nguong HACCP la thong so an toan cua doi xe, server tu lay tu bang
    #: equipment. De ben goi truyen vao thi mot request khai -5 C se bien ke hoach cat dinh thanh
    #: ke hoach lam hong hang, va khong con cach nao phat hien ra.
    rated_power_kw: float = Field(default=120.0, gt=0, le=5000)
    base_temp_c: float = Field(default=-18.0, ge=-50, le=10)
    pre_cool_target_c: float = Field(default=-22.5, ge=-50, le=-15)
    weekday: int = Field(default=1, ge=1, le=7, description="Ngay ISO: 1 = thu Hai .. 7 = chu nhat")


def _plan(session: Session, **kwargs: Any) -> Dict[str, Any]:
    """Goi engine va dich loi: 400 cho tham so sai, 409 cho server thieu cau hinh nghiep vu."""
    try:
        return ai_energy.calculate_peak_shaving_plan(session, **kwargs)
    except ai_energy.PeakShavingConfigError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/peak-shaving/schedule", dependencies=[Depends(AiRoles)])
def get_peak_shaving_schedule(
    weekday: int = Query(default=1, ge=1, le=7, description="Ngay ISO: 1 = thu Hai .. 7 = chu nhat"),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Tra ve ke hoach dieu phoi phu tai 24h suy ra tu bieu gia EVN dang hieu luc."""
    return _plan(session, weekday=weekday)


@router.post("/peak-shaving/simulate", dependencies=[Depends(AiRoles)])
def simulate_peak_shaving(
    payload: PeakShavingSimulateRequest,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Gia lap hieu qua cat dinh voi cong suat va nhiet do van hanh tuy bien."""
    return _plan(
        session,
        rated_power_kw=payload.rated_power_kw,
        base_temp_c=payload.base_temp_c,
        pre_cool_target_c=payload.pre_cool_target_c,
        weekday=payload.weekday,
    )


@router.get("/predictive-maintenance/diagnostics", dependencies=[Depends(AiRoles)])
def get_pdm_diagnostics(
    equipment_id: Optional[int] = Query(default=None, description="ID thiet bi can chan doan rieng"),
    session: Session = Depends(get_session),
) -> List[Dict[str, Any]]:
    """Chan doan suc khoe co khi ISO 10816-3 va suy thoai COP toan bo thiet bi."""
    return ai_energy.diagnose_predictive_maintenance(session, equipment_id=equipment_id)
