"""
Connector B: Home Assistant Metering -> Backend Billing -> Invoice Ninja

Doc CHI SO TICH LUY cua cong to dien tu Home Assistant, gui sang backend de backend
tinh delta kWh + bieu gia EVN TOU, roi xuat hoa don thuong mai vao Invoice Ninja.

Nguyen tac phan cong trach nhiem (day la diem khac biet lon nhat cua ban viet lai nay):

  Backend moi la nguoi quyet dinh so lieu. Connector nay KHONG tinh tien, KHONG giu
  don gia, KHONG tu phan bo kWh theo khung gio. Moi thu do da duoc lam dung o
  backend/app/services/billing.py:
    - delta kWh tinh tu 2 lan doc cong to, co chan so lieu vo ly (khong am tham "boc");
    - chia kWh theo 3 khung gio EVN that, tu telemetry theo phut; khi khong du du lieu
      thi uoc luong theo ty le gio va DANH DAU RO la uoc luong;
    - luu MeterReading de ky sau co goc, nen ky dau tien thieu goc se bao loi chu
      khong xuat hoa don 0 dong.

  Vi sao connector phai bo het don gia cua rieng no: ban cu nhan
  `SERVICE_RATE_PER_KWH` va 3 muc gia EVN tu env cua connector, roi tinh
  `total = kwh x SERVICE_RATE_PER_KWH` - tuc TIEN DIEN KHONG BAO GIO DUOC THU.
  Phan TOU tinh ra chi bi nem vao mot dong ghi chu co cost = 0. Hai he don gia
  o hai noi chac chan lech nhau, va mot trong hai se sai.

Bao mat:
  - Moi request phai mang header X-Connector-API-Key khop CONNECTOR_API_KEY.
  - tenant_code -> Invoice Ninja client_id lay tu TENANT_CLIENT_MAP phia server.
    Nguoi goi khong tu khai duoc client_id.
  - SIMULATION_MODE khong bao gio duoc phep nhan chi so cong to tu nguoi goi khi
    dang chay that: `simulated_reading_kwh` bi tu choi (422) neu SIMULATION_MODE=false.

Idempotency:
  Khoa that nam o backend (cot unique `billed_invoices.external_invoice_id`), khong
  phai file JSON trong container - file thi mat khi restart. Flow:
    1. POST /api/ingest/billing  -> backend tra ve hoa don (hoac hoa don cu, duplicated_call)
    2. Neu hoa don da co external_invoice_id -> ky nay da xuat, dung lai.
    3. Tao hoa don Invoice Ninja.
    4. PATCH /api/ingest/billing/{id}/external-reference de gan ID that ve backend.
  Buoc 4 ma that bai thi van tra ve success cho nguoi goi (hoa don IN da ton tai that)
  nhung ghi Dead-Letter Queue va danh dau external_reference_recorded=false de doi soat.
"""

import hmac
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("HA_InvoiceNinja_Bridge")

STATE_DIR = Path(os.getenv("CONNECTOR_STATE_DIR") or (Path(__file__).resolve().parent / "data"))
DEAD_LETTER_FILE = STATE_DIR / "dead_letter_queue.jsonl"

HASS_URL = os.getenv("HASS_URL", "").rstrip("/")
HASS_TOKEN = os.getenv("HASS_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
BACKEND_CONNECTOR_API_KEY = os.getenv("BACKEND_CONNECTOR_API_KEY", "")
NINJA_URL = os.getenv("INVOICE_NINJA_URL", "").rstrip("/")
NINJA_API_TOKEN = os.getenv("INVOICE_NINJA_TOKEN", "")
CONNECTOR_API_KEY = os.getenv("CONNECTOR_API_KEY", "")
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").strip().lower() == "true"

HA_TIMEOUT_SECONDS = 5
BACKEND_TIMEOUT_SECONDS = 20
NINJA_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = float(os.getenv("RETRY_BACKOFF_SECONDS", "1.0"))

#: Ma khung gio EVN ma backend tra ve trong `kwh_by_band` -> ten san pham tren hoa don.
BAND_PRODUCT_KEYS = {
    "PEAK": ("EVN_PEAK_ENERGY", "Dien nang gio cao diem (EVN)"),
    "NORMAL": ("EVN_NORMAL_ENERGY", "Dien nang gio binh thuong (EVN)"),
    "OFF_PEAK": ("EVN_OFF_PEAK_ENERGY", "Dien nang gio thap diem (EVN)"),
}
SERVICE_PRODUCT_KEY = "COLD_STORAGE_SERVICE"
ENTITY_ID_PATTERN = r"^[a-z0-9_]+\.[a-z0-9_]+$"


def load_tenant_map() -> Dict[str, str]:
    raw = os.getenv("TENANT_CLIENT_MAP", "{}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"TENANT_CLIENT_MAP is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("TENANT_CLIENT_MAP must be a JSON object of tenant_code -> client_id")
    return {str(k): str(v) for k, v in parsed.items()}


TENANT_CLIENT_MAP = load_tenant_map()


class BillingTriggerRequest(BaseModel):
    tenant_code: str = Field(min_length=1, max_length=60)
    sensor_entity_id: str = Field(min_length=1, max_length=200, pattern=ENTITY_ID_PATTERN)
    #: "YYYY-MM". Bo trong thi lay thang da ket thuc gan nhat (dung cho cron chay dau thang).
    billing_period: Optional[str] = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    #: Cho phep ky tuy bien (vd. tu ngay 15 den ngay 15). Uu tien cao hon billing_period.
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    #: Chi dung khi SIMULATION_MODE=true. Day la CHI SO TICH LUY, khong phai delta.
    simulated_reading_kwh: Optional[float] = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _explicit_period_must_be_complete(self) -> "BillingTriggerRequest":
        if bool(self.period_start) != bool(self.period_end):
            raise ValueError("period_start va period_end phai di kem nhau.")
        if self.period_start and self.period_end and self.period_end <= self.period_start:
            raise ValueError("period_end phai sau period_start.")
        return self


def validate_config() -> None:
    if not CONNECTOR_API_KEY:
        raise RuntimeError(
            "CONNECTOR_API_KEY is not set. Refusing to start an unauthenticated billing endpoint."
        )
    if SIMULATION_MODE:
        return
    if not (HASS_URL and HASS_TOKEN):
        raise RuntimeError(
            "HASS_URL / HASS_TOKEN are not set. Set them, or start with SIMULATION_MODE=true."
        )
    if not (BACKEND_URL and BACKEND_CONNECTOR_API_KEY):
        raise RuntimeError(
            "BACKEND_URL / BACKEND_CONNECTOR_API_KEY are not set. Connector nay khong tu tinh "
            "tien, nen khong the chay neu thieu backend."
        )
    if not (NINJA_URL and NINJA_API_TOKEN):
        raise RuntimeError(
            "INVOICE_NINJA_URL / INVOICE_NINJA_TOKEN are not set. "
            "Set them, or start with SIMULATION_MODE=true."
        )
    if not TENANT_CLIENT_MAP:
        raise RuntimeError(
            "TENANT_CLIENT_MAP rong. Khong the xuat hoa don khi chua anh xa tenant nao "
            "sang client cua Invoice Ninja."
        )


validate_config()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Connector B ready (simulation_mode=%s, tenants=%d, backend=%s)",
        SIMULATION_MODE,
        len(TENANT_CLIENT_MAP),
        BACKEND_URL or "<not set>",
    )
    yield


app = FastAPI(
    title="Home Assistant to Invoice Ninja Metering Bridge",
    description=(
        "Reads cumulative meter state from Home Assistant, delegates all pricing to the "
        "ThermalBiz backend, and issues the commercial invoice in Invoice Ninja"
    ),
    lifespan=lifespan,
)


def require_api_key(x_connector_api_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_connector_api_key, CONNECTOR_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid connector API key")


def resolve_client_id(tenant_code: str) -> str:
    client_id = TENANT_CLIENT_MAP.get(tenant_code)
    if not client_id:
        raise HTTPException(
            status_code=404,
            detail=f"tenant_code '{tenant_code}' is not mapped to an Invoice Ninja client",
        )
    return client_id


# --------------------------------------------------------------------------- #
# Ky billing
# --------------------------------------------------------------------------- #
def _as_naive_utc(value: datetime) -> datetime:
    """Backend luu datetime naive-UTC (SQLite khong giu tzinfo). Gui aware sang se lech ky."""
    if value.tzinfo is None:
        return value.replace(microsecond=0)
    return value.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def _month_bounds(year: int, month: int) -> Tuple[datetime, datetime]:
    """[00:00 ngay dau thang, 00:00 ngay dau thang ke tiep) - khop month_bounds cua backend."""
    return datetime(year, month, 1), datetime(year + (month == 12), (month % 12) + 1, 1)


def _last_completed_month(now: datetime) -> Tuple[int, int]:
    return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)


def resolve_period(req: BillingTriggerRequest) -> Tuple[datetime, datetime]:
    if req.period_start and req.period_end:
        return _as_naive_utc(req.period_start), _as_naive_utc(req.period_end)

    if req.billing_period:
        year, month = (int(part) for part in req.billing_period.split("-"))
    else:
        year, month = _last_completed_month(datetime.now(timezone.utc))

    start, end = _month_bounds(year, month)
    return start, end


def invoice_number(tenant_code: str, period_start: datetime) -> str:
    """So hoa don co dinh de doi soat.

    Day la cong cu doi chieu, KHONG phai khoa chong trung: Invoice Ninja khong duoc
    kiem chung la co rang buoc unique tren `number`. Khoa that la cot unique
    `external_invoice_id` o backend.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "-", tenant_code).strip("-").upper()[:24] or "TENANT"
    return f"ESC-{slug}-{period_start.strftime('%Y%m')}"


# --------------------------------------------------------------------------- #
# Doc cong to Home Assistant
# --------------------------------------------------------------------------- #
def read_meter_cumulative(entity_id: str) -> float:
    try:
        response = requests.get(
            f"{HASS_URL}/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {HASS_TOKEN}"},
            timeout=HA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Khong doc duoc Home Assistant (%s): %s", entity_id, exc)
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Home Assistant for '{entity_id}': {exc}",
        ) from exc

    state = response.json()
    raw = state.get("state")
    if raw in (None, "unavailable", "unknown"):
        raise HTTPException(
            status_code=503,
            detail=f"Sensor '{entity_id}' reported state '{raw}'",
        )
    try:
        cumulative = float(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail=f"Sensor '{entity_id}' returned a non-numeric reading"
        ) from exc

    if cumulative < 0:
        raise HTTPException(
            status_code=503,
            detail=f"Sensor '{entity_id}' returned a negative cumulative reading ({cumulative})",
        )
    return cumulative


# --------------------------------------------------------------------------- #
# Backend: nguon su that ve so lieu
# --------------------------------------------------------------------------- #
def backend_headers() -> Dict[str, str]:
    return {"X-Connector-Api-Key": BACKEND_CONNECTOR_API_KEY, "Content-Type": "application/json"}


def request_invoice_from_backend(
    tenant_code: str,
    entity_id: str,
    period_start: datetime,
    period_end: datetime,
    current_reading_kwh: float,
    source: str,
) -> Dict[str, Any]:
    """Goi backend tinh hoa don.

    KHONG gui previous_reading_kwh: backend tu lay chi so cuoi ky truoc trong MeterReading.
    Neu chua co goc, backend bao 422 'missing_baseline' - dung hon la am tham xuat hoa
    don 0 dong roi ky sau van khong co goc.
    """
    body = {
        "tenant_code": tenant_code,
        "entity_id": entity_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "current_reading_kwh": current_reading_kwh,
        "source": source,
    }
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/ingest/billing",
            json=body,
            headers=backend_headers(),
            timeout=BACKEND_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.error("Khong ket noi duoc backend %s: %s", BACKEND_URL, exc)
        raise HTTPException(status_code=502, detail=f"Backend integration error: {exc}") from exc

    # 409 = cong to quay so / tham chieu trung; 422 = du lieu khong tinh duoc;
    # 503 = backend chua cau hinh bieu gia. Nguyen van de nguoi van hanh thay dung benh.
    if response.status_code >= 400:
        detail = _error_detail(response)
        status_code = response.status_code if 400 <= response.status_code < 500 else 502
        logger.error("Backend tu choi tinh hoa don (%d): %s", response.status_code, detail)
        raise HTTPException(status_code=status_code, detail=f"Backend billing error: {detail}")

    return response.json()


def link_external_reference(backend_invoice_id: int, external_id: str) -> bool:
    """Gan ID hoa don Invoice Ninja ve backend. Tra ve False neu that bai (da ghi DLQ).

    Day la buoc quyet dinh viec ky nay co bi xuat hoa don lan hai hay khong, nen phai
    retry: hoa don Invoice Ninja da ton tai that roi, khong the "thu lai luc khac".
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.patch(
                f"{BACKEND_URL}/api/ingest/billing/{backend_invoice_id}/external-reference",
                json={"external_invoice_id": external_id},
                headers=backend_headers(),
                timeout=BACKEND_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.warning("Gan external reference lan %d that bai (loi mang): %s", attempt, exc)
            _backoff(attempt)
            continue

        if response.status_code < 400:
            return True

        # 409 = tham chieu da duoc gan (lan chay truoc da thanh cong) -> coi nhu xong.
        if response.status_code == 409:
            logger.warning("Backend bao tham chieu da ton tai (%d), coi nhu da gan xong.", response.status_code)
            return True

        # 4xx khac = loi contract, retry vo ich.
        if response.status_code < 500:
            logger.error(
                "Backend tu choi external reference (%d): %s",
                response.status_code,
                _error_detail(response),
            )
            return False

        logger.warning("Gan external reference lan %d that bai: HTTP %d", attempt, response.status_code)
        _backoff(attempt)

    logger.error("Khong gan duoc external reference ve backend sau %d lan thu.", MAX_RETRIES)
    return False


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail[:500]
        if detail is not None:
            return json.dumps(detail, ensure_ascii=False)[:500]
    return json.dumps(body, ensure_ascii=False)[:500]


# --------------------------------------------------------------------------- #
# Invoice Ninja
# --------------------------------------------------------------------------- #
def build_line_items(invoice: Dict[str, Any]) -> list:
    """Mot dong cho moi khung gio co kWh > 0, cong mot dong phi dich vu bao quan.

    Don gia va so kWh lay nguyen van tu backend. Connector khong tu dat ra gia nao.
    """
    breakdown = invoice.get("breakdown") or {}
    prices: Dict[str, Any] = breakdown.get("prices_vnd_per_kwh") or {}
    kwh_by_band: Dict[str, Any] = invoice.get("kwh_by_band") or {}

    items = []
    for band, (product_key, label) in BAND_PRODUCT_KEYS.items():
        kwh = float(kwh_by_band.get(band) or 0.0)
        if kwh <= 0:
            continue
        price = int(prices.get(band, 0))
        items.append(
            {
                "type_id": "1",
                "product_key": product_key,
                "notes": f"{label}: {kwh:,.2f} kWh x {price:,d} d/kWh",
                "cost": price,
                "quantity": round(kwh, 3),
            }
        )

    service_rate = int(breakdown.get("service_rate_per_kwh") or 0)
    total_kwh = float(invoice.get("total_kwh") or 0.0)
    if service_rate > 0 and total_kwh > 0:
        items.append(
            {
                "type_id": "1",
                "product_key": SERVICE_PRODUCT_KEY,
                "notes": f"Phi quan ly & bao quan lanh: {total_kwh:,.2f} kWh x {service_rate:,d} d/kWh",
                "cost": service_rate,
                "quantity": round(total_kwh, 3),
            }
        )
    return items


def build_public_notes(invoice: Dict[str, Any], tenant_code: str) -> str:
    """Ghi chu tren hoa don. Noi ro so lieu la cua backend, va noi ro khi la UOC LUONG."""
    breakdown = invoice.get("breakdown") or {}
    lines = [
        f"Ky thanh toan: {invoice.get('period_start')} -> {invoice.get('period_end')}",
        f"Ma khach hang noi bo: {tenant_code}",
        f"So hoa don he thong (ThermalBiz): #{invoice.get('id')}",
        f"Tong dien nang: {float(invoice.get('total_kwh') or 0.0):,.2f} kWh",
        f"Tien dien: {int(invoice.get('electricity_vnd') or 0):,d} VND",
        f"Phi dich vu: {int(invoice.get('service_fee_vnd') or 0):,d} VND",
        f"Tong cong: {int(invoice.get('total_vnd') or 0):,d} VND",
    ]

    split_method = breakdown.get("split_method")
    if split_method == "hours_estimate":
        lines.append(
            "LUU Y: Phan bo kWh theo 3 khung gio la UOC LUONG theo ty le so gio, "
            "vi ky nay khong du du lieu cong to theo tung phut. Tong kWh va tong tien "
            "van la so that; chi phan chia theo khung gio la uoc luong."
        )
    elif split_method == "telemetry_scaled":
        lines.append(
            "LUU Y: Du lieu cong to theo phut khong phu het ky nay. Tong kWh va tong tien "
            "lay theo chi so cong to hoa don (so that); ty le giua cac khung gio la SUY RA "
            "tu phan da do duoc."
        )
    elif split_method == "telemetry":
        lines.append("Phan bo kWh theo khung gio tinh tu du lieu cong to do duoc.")

    for warning in breakdown.get("warnings") or []:
        lines.append(f"Canh bao du lieu: {warning}")

    if breakdown.get("reading_start_kwh") is not None:
        lines.append(
            "Chi so cong to: {start} -> {end} kWh".format(
                start=f"{float(breakdown['reading_start_kwh']):,.2f}",
                end=f"{float(breakdown.get('reading_end_kwh') or 0.0):,.2f}",
            )
        )
    return "\n".join(lines)


def _backoff(attempt: int) -> None:
    if attempt < MAX_RETRIES and RETRY_BACKOFF_SECONDS > 0:
        time.sleep(RETRY_BACKOFF_SECONDS * attempt)


def create_ninja_invoice(client_id: str, number: str, invoice: Dict[str, Any], tenant_code: str) -> Dict[str, Any]:
    line_items = build_line_items(invoice)
    if not line_items:
        # Khong co dong nao nghia la backend tra ve 0 kWh ma khong bi chan o tren.
        # Tu choi hon la xuat mot hoa don rong khong co gia tri phap ly.
        raise HTTPException(
            status_code=502,
            detail="Backend returned an invoice with no billable line items; refusing to create an empty invoice.",
        )

    payload = {
        "client_id": client_id,
        "number": number,
        "line_items": line_items,
        "public_notes": build_public_notes(invoice, tenant_code),
    }

    last_error: Optional[str] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                f"{NINJA_URL}/api/v1/invoices",
                headers={"X-Api-Token": NINJA_API_TOKEN, "Content-Type": "application/json"},
                json=payload,
                timeout=NINJA_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            last_error = str(exc)
            logger.warning("Gui hoa don lan %d that bai (loi mang): %s", attempt, exc)
            _backoff(attempt)
            continue

        if response.status_code < 400:
            return response.json()

        # 4xx = payload/co cau hinh sai. Retry khong doi duoc ket qua.
        if response.status_code < 500:
            detail = _error_detail(response)
            logger.error("Invoice Ninja tu choi hoa don (%d): %s", response.status_code, detail)
            raise HTTPException(
                status_code=502, detail=f"Invoice Ninja rejected the invoice: {detail}"
            )

        last_error = f"HTTP {response.status_code}: {_error_detail(response)}"
        logger.warning("Gui hoa don lan %d that bai: %s", attempt, last_error)
        _backoff(attempt)

    _log_dead_letter(
        {
            "stage": "invoice_ninja",
            "tenant_code": tenant_code,
            "invoice_number": number,
            "backend_invoice_id": invoice.get("id"),
            "total_vnd": invoice.get("total_vnd"),
            "error": last_error,
            "payload": payload,
        }
    )
    raise HTTPException(status_code=502, detail=f"Invoice Ninja error after retries: {last_error}")


def extract_invoice_id(response: Any) -> Optional[str]:
    """Invoice Ninja v5 boc moi resource trong {"data": {...}}."""
    if not isinstance(response, dict):
        return None
    data = response.get("data", response)
    if not isinstance(data, dict):
        return None
    raw_id = data.get("id")
    return str(raw_id) if raw_id not in (None, "") else None


# --------------------------------------------------------------------------- #
# Dead-letter queue
# --------------------------------------------------------------------------- #
def _log_dead_letter(entry: Dict[str, Any]) -> None:
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(DEAD_LETTER_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Khong ghi duoc Dead Letter Queue: %s", exc)


def _dead_letter_count() -> int:
    """Dem so dong DLQ ma khong nap ca file: healthcheck bi goi lien tuc tu Docker."""
    if not DEAD_LETTER_FILE.exists():
        return 0
    count = 0
    try:
        with open(DEAD_LETTER_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
    except OSError as exc:
        logger.error("Khong doc duoc Dead Letter Queue: %s", exc)
    return count


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "ha-invoiceninja-bridge",
        "simulation_mode": SIMULATION_MODE,
        "mapped_tenants": len(TENANT_CLIENT_MAP),
        "backend_configured": bool(BACKEND_URL),
        "dead_letter_count": _dead_letter_count(),
        "pricing_owner": "backend" if not SIMULATION_MODE else "not_calculated",
    }


@app.post("/api/generate-invoice", dependencies=[Depends(require_api_key)])
def generate_usage_invoice(req: BillingTriggerRequest) -> Dict[str, Any]:
    client_id = resolve_client_id(req.tenant_code)
    period_start, period_end = resolve_period(req)
    number = invoice_number(req.tenant_code, period_start)

    logger.info(
        "Chot so tenant %s (client %s), sensor %s, ky %s -> %s",
        req.tenant_code,
        client_id,
        req.sensor_entity_id,
        period_start.isoformat(),
        period_end.isoformat(),
    )

    if SIMULATION_MODE:
        return _simulate(req, client_id, period_start, period_end, number)

    if req.simulated_reading_kwh is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "simulated_reading_kwh chi duoc dung khi SIMULATION_MODE=true. "
                "Tu choi de nguoi goi khong tu khai duoc san luong dien tren duong chay that."
            ),
        )

    cumulative = read_meter_cumulative(req.sensor_entity_id)

    invoice = request_invoice_from_backend(
        tenant_code=req.tenant_code,
        entity_id=req.sensor_entity_id,
        period_start=period_start,
        period_end=period_end,
        current_reading_kwh=cumulative,
        source="HA",
    )

    if invoice.get("external_invoice_id"):
        logger.info(
            "Ky %s -> %s da co hoa don Invoice Ninja %s, bo qua.",
            period_start,
            period_end,
            invoice["external_invoice_id"],
        )
        return {
            "status": "already_billed",
            "invoice_number": number,
            "external_invoice_id": invoice["external_invoice_id"],
            "backend_invoice": invoice,
        }

    total_vnd = int(invoice.get("total_vnd") or 0)
    if total_vnd <= 0:
        logger.info("Ky %s -> %s khong phat sinh tien, khong xuat hoa don.", period_start, period_end)
        return {
            "status": "no_charge",
            "invoice_number": number,
            "backend_invoice": invoice,
            "message": "Backend tinh ra 0 VND cho ky nay; khong tao hoa don rong.",
        }

    created = create_ninja_invoice(client_id, number, invoice, req.tenant_code)
    external_id = extract_invoice_id(created)
    if not external_id:
        _log_dead_letter(
            {
                "stage": "invoice_ninja_id_missing",
                "tenant_code": req.tenant_code,
                "invoice_number": number,
                "backend_invoice_id": invoice.get("id"),
                "error": "Invoice Ninja response did not contain data.id",
                "response": created,
            }
        )
        raise HTTPException(
            status_code=502,
            detail="Invoice Ninja accepted the request but returned no invoice id; check the dead-letter queue.",
        )

    recorded = link_external_reference(int(invoice["id"]), external_id)
    if not recorded:
        _log_dead_letter(
            {
                "stage": "backend_external_reference",
                "tenant_code": req.tenant_code,
                "invoice_number": number,
                "backend_invoice_id": invoice.get("id"),
                "external_invoice_id": external_id,
                "error": "PATCH external-reference failed; ky nay co the bi xuat hoa don lan 2 neu goi lai.",
            }
        )

    logger.info("Da xuat hoa don Invoice Ninja %s cho tenant %s", external_id, req.tenant_code)
    return {
        "status": "success",
        "invoice_number": number,
        "external_invoice_id": external_id,
        "external_reference_recorded": recorded,
        "kwh_metered": invoice.get("total_kwh"),
        "electricity_vnd": invoice.get("electricity_vnd"),
        "service_fee_vnd": invoice.get("service_fee_vnd"),
        "total_vnd": total_vnd,
        "split_method": (invoice.get("breakdown") or {}).get("split_method"),
        "line_items": build_line_items(invoice),
        "backend_invoice": invoice,
        "invoice": created,
    }


def _simulate(
    req: BillingTriggerRequest,
    client_id: str,
    period_start: datetime,
    period_end: datetime,
    number: str,
) -> Dict[str, Any]:
    """Che do chay thu: chi cho thay payload, KHONG bia ra tien.

    Connector nay khong giu bieu gia, nen khong the tinh ra VND. Tra ve mot con so
    "gia lap" o day se la noi doi: nguoi dung se tuong he thong da tinh dung.
    """
    if req.simulated_reading_kwh is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "SIMULATION_MODE can `simulated_reading_kwh` (chi so cong to tich luy). "
                "Connector khong tu dat ra san luong."
            ),
        )

    backend_request = {
        "tenant_code": req.tenant_code,
        "entity_id": req.sensor_entity_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "current_reading_kwh": req.simulated_reading_kwh,
        "source": "SIMULATION",
    }
    logger.info("[SIMULATION] Se goi backend: %s", backend_request)
    return {
        "status": "simulated",
        "invoice_number": number,
        "client_id": client_id,
        "backend_request": backend_request,
        "invoice_draft": {
            "client_id": client_id,
            "number": number,
            "line_items": "duoc dung tu kwh_by_band va don gia cua backend",
            "public_notes": "duoc dung tu tong tien va canh bao cua backend",
        },
        "pricing": "not_calculated",
        "note": (
            "Che do mo phong khong tinh tien vi connector khong giu bieu gia. "
            "Muon thay so that, hay chay backend va tat SIMULATION_MODE."
        ),
    }
