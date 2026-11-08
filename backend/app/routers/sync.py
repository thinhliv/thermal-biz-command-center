"""Router cho Multi-Site Edge-to-Cloud Sync Engine.

Nhan du lieu Store-and-Forward tu cac tram bien / kho lanh ve Cloud Command Center:
  - POST /api/sync/push: Day batch tu Edge ve Cloud (bao ve bang X-Connector-Api-Key).
  - GET /api/sync/sites: Danh sach chi nhanh va trang thai ket noi thuc te.
  - GET /api/sync/batches: Lich su cac goi tin da dong bo.
  - GET /api/sync/status: Tong quan chi so mang dong bo toan quoc.

Site la du lieu danh muc (master data) duoc seed truoc, giong Equipment va TariffBand.
Khong co endpoint tu tao Site: neu co thi bat ky ai giu CONNECTOR_API Key cung them
duoc chi nhanh gia vao bao cao mang luoi.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import SyncBatch
from ..security import ThermalRoles, require_connector_key
from ..services import sync as sync_service
from ..timeutil import utcnow

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncPushPayload(BaseModel):
    site_code: str = Field(min_length=1, max_length=32)
    batch_id: str = Field(min_length=1, max_length=64)
    #: Optional vi day la so do phia Edge. Thieu thi Cloud giu nguyen gia tri cu,
    #: khong tu dien 0 hay 45 (0ms/45ms deu la con so bia ve chat luong mang).
    latency_ms: Optional[int] = Field(default=None, ge=0)
    #: So ban ghi con nam trong outbox cua Edge TRUOC goi nay. Chi Edge moi biet.
    pending_records: Optional[int] = Field(default=None, ge=0)
    records: List[Dict[str, Any]] = Field(default_factory=list)


@router.post("/push")
def push_sync_batch(
    payload: SyncPushPayload,
    session: Session = Depends(get_session),
    _: None = Depends(require_connector_key),
) -> Dict[str, Any]:
    """Nhan goi dong bo tu Edge. Bat buoc header X-Connector-Api-Key."""
    try:
        return sync_service.process_sync_batch(
            session=session,
            site_code=payload.site_code,
            batch_id=payload.batch_id,
            records=payload.records,
            latency_ms=payload.latency_ms,
            pending_records=payload.pending_records,
        )
    except sync_service.UnknownSiteError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc


@router.get("/sites", dependencies=[Depends(ThermalRoles)])
def get_sites_health(session: Session = Depends(get_session)) -> List[Dict[str, Any]]:
    """Tra ve danh sach cac chi nhanh/kho lanh kem suc khoe ket noi thoi gian thuc."""
    return sync_service.list_sites_with_health(session)


@router.get("/batches", dependencies=[Depends(ThermalRoles)])
def get_recent_batches(
    site_code: Optional[str] = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> List[Dict[str, Any]]:
    """Tra ve lich su cac goi sync da nap vao Cloud."""
    query = select(SyncBatch).order_by(desc(SyncBatch.received_at))
    if site_code:
        query = query.where(SyncBatch.site_code == site_code)
    batches = list(session.scalars(query.limit(min(limit, 200))))
    return [
        {
            "id": b.id,
            "batch_id": b.batch_id,
            "site_code": b.site_code,
            "received_at": b.received_at.isoformat(),
            "records_count": b.records_count,
            "status": b.status,
            "idempotency_hash": b.idempotency_hash,
        }
        for b in batches
    ]


@router.get("/status", dependencies=[Depends(ThermalRoles)])
def get_sync_network_status(session: Session = Depends(get_session)) -> Dict[str, Any]:
    """Tong quan trang thai mang luoi Edge toan he thong."""
    sites = sync_service.list_sites_with_health(session)
    total_sites = len(sites)
    online_sites = sum(1 for s in sites if s["status"] == "ONLINE")
    offline_sites = total_sites - online_sites
    total_batches = session.scalar(select(func.count(SyncBatch.id))) or 0
    total_records = session.scalar(select(func.sum(SyncBatch.records_count))) or 0

    return {
        "status": "healthy" if offline_sites == 0 else "degraded",
        "total_sites": total_sites,
        "online_sites": online_sites,
        "offline_sites": offline_sites,
        "total_batches_synced": total_batches,
        "total_records_ingested": int(total_records),
        "timestamp": utcnow().isoformat(),
    }
