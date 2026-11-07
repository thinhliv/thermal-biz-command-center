"""Endpoint may-goi-may cho connector (ThingsBoard -> Huong A, Home Assistant -> Huong B).

Bao mat: khoa bang CONNECTOR_API_KEY (so sanh constant-time), khong dung JWT.

Hai nguyen tac nghiep vu:
1. COP LUON duoc tinh lai tu Q_o va N_e o backend. Client khong duoc tu khai COP.
2. Billing nhan CHI SO TICH LUY va tu suy ra delta kWh. Doc cong to khong hop le -> bao loi
   ro rang, khong bao gio "boc" ra mot con so de hoa don van chay.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_session
from ..models import BilledInvoice, Equipment, MeterReading, TelemetrySample
from ..schemas import BillingRequest, BillingResponse, TelemetryIn, TelemetryIngestResult
from ..security import require_connector_key
from ..services import billing, thermal
from ..timeutil import utcnow

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

#: Loi billing -> ma HTTP. 409 = xung dot voi du lieu da luu; 422 = du lieu khong xu ly duoc;
#: 503 = server thieu cau hinh (chua co bieu gia).
_BILLING_ERROR_STATUS = {
    "missing_baseline": 422,
    "counter_rolled_back": status.HTTP_409_CONFLICT,
    "implausible_delta": 422,
    "missing_reading": 422,
    "bad_period": 422,
    "no_tariff": status.HTTP_503_SERVICE_UNAVAILABLE,
}


class TelemetryBatch(BaseModel):
    samples: list[TelemetryIn] = Field(min_length=1, max_length=1000)


class ExternalInvoiceRef(BaseModel):
    """Tham chieu hoa don o he thong ngoai (Invoice Ninja). Column unique -> khong the gan trung."""

    external_invoice_id: str = Field(min_length=1, max_length=64)


@router.get("/health")
def ingest_health(session: Session = Depends(get_session)) -> dict:
    """Public: connector dung de kiem tra backend song hay chet truoc khi day du lieu."""
    equipment_count = len(list(session.scalars(select(Equipment.id))))
    return {
        "status": "ok",
        "equipment_registered": equipment_count,
        "server_time": utcnow().isoformat(),
    }


@router.get("/tenants")
def list_tenants(
    session: Session = Depends(get_session), _: None = Depends(require_connector_key)
) -> dict:
    """Danh sach tenant hop le. Connector hoi o day thay vi de nguoi goi tu khai client_id."""
    rows = session.scalars(
        select(Equipment).where(Equipment.tenant_code.is_not(None), Equipment.is_active.is_(True))
    )
    return {
        "tenants": [
            {
                "tenant_code": e.tenant_code,
                "equipment_code": e.code,
                "equipment_name": e.name,
                "meter_entity_id": e.meter_entity_id,
                "rated_power_kw": e.rated_power_kw,
            }
            for e in rows
        ]
    }


def _load_equipment_by_code(session: Session, codes: set[str]) -> dict[str, Equipment]:
    if not codes:
        return {}
    rows = session.scalars(select(Equipment).where(Equipment.code.in_(codes)))
    return {e.code: e for e in rows}


def _store_sample(session: Session, payload: TelemetryIn, equipment: Equipment) -> list:
    """Luu mot mau va cham diem canh bao. Tra ve cac Alert moi sinh ra."""
    # COP tinh lai tu Q_o / N_e. Thiet bi lanh thieu Q_o -> COP = None, khong nhan so cua client.
    cop = thermal.compute_cop(payload.cooling_capacity_kw, payload.power_kw) if equipment.is_refrigeration else None
    # Lo hoi khong duoc ghi COP; thiet bi lanh khong duoc ghi hieu suat dot
    efficiency_pct = payload.efficiency_pct if equipment.is_combustion else None

    sample = TelemetrySample(
        equipment_id=equipment.id,
        ts=payload.ts or utcnow(),
        temperature_c=payload.temperature_c,
        pressure_bar=payload.pressure_bar,
        power_kw=payload.power_kw,
        cooling_capacity_kw=payload.cooling_capacity_kw if equipment.is_refrigeration else None,
        cop=cop,
        efficiency_pct=efficiency_pct,
        vibration_mm_s=payload.vibration_mm_s,
        energy_kwh_cumulative=payload.energy_kwh_cumulative,
        status=payload.status.value if payload.status else None,
    )
    session.add(sample)
    session.flush()
    return thermal.evaluate_sample(session, equipment, sample)


@router.post("/telemetry", response_model=TelemetryIngestResult, status_code=status.HTTP_201_CREATED)
def ingest_one(
    payload: TelemetryIn,
    session: Session = Depends(get_session),
    _: None = Depends(require_connector_key),
) -> dict:
    equipment = _load_equipment_by_code(session, {payload.equipment_code.strip()}).get(
        payload.equipment_code.strip()
    )
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thiet bi '{payload.equipment_code}' chua duoc dang ky trong he thong.",
        )

    alerts = _store_sample(session, payload, equipment)
    session.commit()
    return {
        "accepted": 1,
        "rejected": [],
        "alerts_raised": [thermal.serialize_alert(a) for a in alerts],
    }


@router.post("/telemetry/batch", response_model=TelemetryIngestResult)
def ingest_batch(
    payload: TelemetryBatch,
    session: Session = Depends(get_session),
    _: None = Depends(require_connector_key),
) -> dict:
    """Day nhieu mau mot luc.

    Kiem tra dang ky thiet bi TRUOC khi ghi, vi mot lan rollback se keo theo tat ca mau
    da luu truoc do va lam so `accepted` thanh noi doi.
    """
    codes = {s.equipment_code.strip() for s in payload.samples}
    known = _load_equipment_by_code(session, codes)

    rejected: list[dict] = [
        {
            "index": index,
            "equipment_code": sample.equipment_code,
            "error": f"Thiet bi '{sample.equipment_code}' chua duoc dang ky trong he thong.",
        }
        for index, sample in enumerate(payload.samples)
        if sample.equipment_code.strip() not in known
    ]

    all_alerts: list = []
    accepted = 0
    for sample in payload.samples:
        equipment = known.get(sample.equipment_code.strip())
        if equipment is None:
            continue
        all_alerts.extend(_store_sample(session, sample, equipment))
        accepted += 1

    session.commit()
    return {
        "accepted": accepted,
        "rejected": rejected,
        "alerts_raised": [thermal.serialize_alert(a) for a in all_alerts],
    }


def _resolve_previous_reading(session: Session, tenant_code: str, period_start) -> float | None:
    """Chi so cuoi ky truoc chinh la chi so dau ky nay. Khong co -> None de bao loi ro rang."""
    previous = session.scalars(
        select(MeterReading)
        .where(MeterReading.tenant_code == tenant_code, MeterReading.period_end <= period_start)
        .order_by(MeterReading.period_end.desc())
        .limit(1)
    ).first()
    return previous.reading_end_kwh if previous else None


@router.post("/billing", response_model=BillingResponse)
def generate_invoice(
    payload: BillingRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_connector_key),
) -> dict:
    """Xuat hoa don dien theo ky. Idempotent: goi lai dung ky -> tra ve hoa don cu."""
    settings = get_settings()
    equipment = session.scalars(
        select(Equipment).where(Equipment.tenant_code == payload.tenant_code, Equipment.is_active.is_(True))
    ).first()

    previous = payload.previous_reading_kwh
    if previous is None:
        previous = _resolve_previous_reading(session, payload.tenant_code, payload.period_start)

    try:
        invoice = billing.build_invoice(
            session=session,
            tenant_code=payload.tenant_code,
            period_start=payload.period_start,
            period_end=payload.period_end,
            previous_kwh=previous,
            current_kwh=payload.current_reading_kwh,
            service_rate_per_kwh=settings.service_rate_per_kwh,
            equipment_id=equipment.id if equipment else None,
            rated_power_kw=equipment.rated_power_kw if equipment else None,
            entity_id=payload.entity_id or (equipment.meter_entity_id if equipment else None),
            source=payload.source,
        )
    except billing.BillingError as exc:
        session.rollback()
        raise HTTPException(
            status_code=_BILLING_ERROR_STATUS.get(exc.code, 422),
            detail=exc.message,
        ) from exc

    session.commit()
    return invoice


@router.patch("/billing/{invoice_id}/external-reference")
def link_external_invoice(
    invoice_id: int,
    payload: ExternalInvoiceRef,
    session: Session = Depends(get_session),
    _: None = Depends(require_connector_key),
) -> dict:
    """Gan ID hoa don Invoice Ninja vao hoa don da tinh o backend.

    Day moi la khoa idempotency BEN VUNG cua connector: file JSON trong container
    mat khi restart, con cot nay thi khong. Lan chay sau thay external_invoice_id
    da co thi biet ky nay da xuat hoa don that, khong tao ban doi.
    """
    invoice = session.get(BilledInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Khong tim thay hoa don #{invoice_id} de gan tham chieu ngoai.",
        )

    if invoice.external_invoice_id == payload.external_invoice_id:
        return _external_ref_payload(invoice, "unchanged")

    if invoice.external_invoice_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Hoa don #{invoice_id} da gan tham chieu '{invoice.external_invoice_id}'. "
                f"Tu choi ghi de bang '{payload.external_invoice_id}'."
            ),
        )

    holder = session.scalars(
        select(BilledInvoice).where(BilledInvoice.external_invoice_id == payload.external_invoice_id)
    ).first()
    if holder is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tham chieu '{payload.external_invoice_id}' da thuoc hoa don #{holder.id}.",
        )

    invoice.external_invoice_id = payload.external_invoice_id
    session.commit()
    return _external_ref_payload(invoice, "linked")


def _external_ref_payload(invoice: BilledInvoice, outcome: str) -> dict:
    return {
        "status": outcome,
        "invoice_id": invoice.id,
        "external_invoice_id": invoice.external_invoice_id,
        "tenant_code": invoice.tenant_code,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
    }
