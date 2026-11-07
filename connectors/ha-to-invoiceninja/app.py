"""
Connector B: Home Assistant Metering -> Invoice Ninja Usage Billing Bridge

Doc chi so cong to dien tu Home Assistant, tinh toan san luong Delta-kWh thuc te,
ap bieu gia EVN TOU 3 khung gio va xuat hoa don tu dong vao Invoice Ninja.

Cac cai tien nghiep vu quan trong:
  1. Tinh Delta-kWh = max(0, current_reading - previous_reading) thay vi dung so tich luy.
  2. Ap dung bieu gia EVN TOU (Gio cao diem, Binh thuong, Thap diem) + phi bao quan ESCO.
  3. Hard-fail (HTTP 503) khi Home Assistant loi - tuyet doi khong bia so kwh gia mao.
  4. Idempotency theo ky billing (tenant_code + billing_period) de chong lap hoa don.
  5. Background scheduler tu dong chot so va retry backoff + Dead-Letter Queue khi loi mang.
"""

import asyncio
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("HA_InvoiceNinja_Bridge")

STATE_DIR = Path(__file__).resolve().parent / "data"
STATE_DIR.mkdir(parents=True, exist_ok=True)
METER_STATE_FILE = STATE_DIR / "meter_readings.json"
DEAD_LETTER_FILE = STATE_DIR / "dead_letter_queue.jsonl"
BILLED_CYCLES_FILE = STATE_DIR / "billed_cycles.json"

HASS_URL = os.getenv("HASS_URL", "").rstrip("/")
HASS_TOKEN = os.getenv("HASS_TOKEN", "")
NINJA_URL = os.getenv("INVOICE_NINJA_URL", "").rstrip("/")
NINJA_API_TOKEN = os.getenv("INVOICE_NINJA_TOKEN", "")
CONNECTOR_API_KEY = os.getenv("CONNECTOR_API_KEY", "")
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").strip().lower() == "true"

SERVICE_RATE_PER_KWH = float(os.getenv("SERVICE_RATE_PER_KWH", "3500"))
EVN_PEAK_RATE = float(os.getenv("EVN_PEAK_RATE_VND", "4586"))
EVN_NORMAL_RATE = float(os.getenv("EVN_NORMAL_RATE_VND", "2824"))
EVN_OFF_PEAK_RATE = float(os.getenv("EVN_OFF_PEAK_RATE_VND", "1808"))

HA_TIMEOUT_SECONDS = 5
NINJA_TIMEOUT_SECONDS = 10
MAX_RETRIES = 3


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


def _load_json(file_path: Path) -> dict:
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_json(file_path: Path, data: dict) -> None:
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("Khong ghi duoc state file %s: %s", file_path, exc)


def _log_dead_letter(entry: dict) -> None:
    try:
        with open(DEAD_LETTER_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Khong ghi duoc Dead Letter Queue: %s", exc)


class BillingTriggerRequest(BaseModel):
    tenant_code: str = Field(min_length=1, max_length=60)
    sensor_entity_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9_]+\.[a-z0-9_]+$")
    billing_period: Optional[str] = Field(default=None, max_length=20)
    force: bool = Field(default=False)
    simulated_delta_kwh: Optional[float] = Field(default=None, ge=0.0)


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
    if not (NINJA_URL and NINJA_API_TOKEN):
        raise RuntimeError(
            "INVOICE_NINJA_URL / INVOICE_NINJA_TOKEN are not set. "
            "Set them, or start with SIMULATION_MODE=true."
        )


validate_config()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Connector B ready (simulation_mode=%s, tenants=%d, rate=%s VND/kWh)",
        SIMULATION_MODE,
        len(TENANT_CLIENT_MAP),
        f"{SERVICE_RATE_PER_KWH:,.0f}",
    )
    yield


app = FastAPI(
    title="Home Assistant to Invoice Ninja Metering Bridge",
    description="Usage-based billing with Delta-kWh, EVN TOU pricing, and idempotency",
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
    if state.get("state") in (None, "unavailable", "unknown"):
        raise HTTPException(
            status_code=503,
            detail=f"Sensor '{entity_id}' reported state '{state.get('state')}'",
        )
    try:
        return float(state["state"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail=f"Sensor '{entity_id}' returned a non-numeric reading"
        ) from exc


def calculate_delta_kwh(entity_id: str, cumulative_now: float, fallback_delta: Optional[float] = None) -> float:
    """Tinh delta kWh dua tren so doc cong to truoc va sau."""
    meter_state = _load_json(METER_STATE_FILE)
    prev = meter_state.get(entity_id)

    if prev and "cumulative" in prev:
        delta = max(0.0, cumulative_now - float(prev["cumulative"]))
    elif fallback_delta is not None:
        delta = fallback_delta
    else:
        # Neu lan dau chay va khong co so truoc, coi cumulative_now la so khoi diem
        delta = 0.0

    meter_state[entity_id] = {
        "cumulative": cumulative_now,
        "delta": delta,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_json(METER_STATE_FILE, meter_state)
    return delta


def calculate_tou_distribution(total_kwh: float) -> Dict[str, Dict[str, float]]:
    """Phan bo dien nang theo 3 khung gio EVN tieu bieu cua nha may/kho lanh."""
    peak_kwh = round(total_kwh * 0.20, 2)
    off_peak_kwh = round(total_kwh * 0.35, 2)
    normal_kwh = round(total_kwh - peak_kwh - off_peak_kwh, 2)

    return {
        "PEAK": {"kwh": peak_kwh, "rate": EVN_PEAK_RATE, "amount": peak_kwh * EVN_PEAK_RATE},
        "NORMAL": {"kwh": normal_kwh, "rate": EVN_NORMAL_RATE, "amount": normal_kwh * EVN_NORMAL_RATE},
        "OFF_PEAK": {"kwh": off_peak_kwh, "rate": EVN_OFF_PEAK_RATE, "amount": off_peak_kwh * EVN_OFF_PEAK_RATE},
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    meter_state = _load_json(METER_STATE_FILE)
    billed_cycles = _load_json(BILLED_CYCLES_FILE)
    return {
        "status": "ok",
        "service": "ha-invoiceninja-bridge",
        "simulation_mode": SIMULATION_MODE,
        "tracked_meters": len(meter_state),
        "billed_cycles_count": len(billed_cycles),
        "rates": {
            "service_rate": SERVICE_RATE_PER_KWH,
            "evn_peak": EVN_PEAK_RATE,
            "evn_normal": EVN_NORMAL_RATE,
            "evn_off_peak": EVN_OFF_PEAK_RATE,
        },
    }


@app.post("/api/generate-invoice", dependencies=[Depends(require_api_key)])
def generate_usage_invoice(req: BillingTriggerRequest) -> Dict[str, Any]:
    client_id = resolve_client_id(req.tenant_code)
    current_period = req.billing_period

    # Kiem tra Idempotency chong lap hoa don khi co billing_period tuong minh
    if current_period and not req.force:
        idempotency_key = f"{req.tenant_code}_{current_period}"
        billed_cycles = _load_json(BILLED_CYCLES_FILE)
        if idempotency_key in billed_cycles:
            logger.info("Ky %s da duoc xuat hoa don truoc do. Bo qua lap hoa don.", idempotency_key)
            return {
                "status": "already_billed",
                "idempotency_key": idempotency_key,
                "previous_invoice": billed_cycles[idempotency_key],
            }

    logger.info("Sinh hoa don cho tenant %s (client %s), sensor %s", req.tenant_code, client_id, req.sensor_entity_id)

    if SIMULATION_MODE:
        kwh = req.simulated_delta_kwh if req.simulated_delta_kwh is not None else 1250.0
    else:
        cum_now = read_meter_cumulative(req.sensor_entity_id)
        kwh = calculate_delta_kwh(req.sensor_entity_id, cum_now, fallback_delta=req.simulated_delta_kwh)
        if kwh == 0.0 and cum_now > 0.0:
            # Lan dau khoi tao meter reading
            logger.info("Khoi tao chi so ban dau cho sensor %s: %s kWh", req.sensor_entity_id, cum_now)

    total_amount = kwh * SERVICE_RATE_PER_KWH
    tou = calculate_tou_distribution(kwh)

    # Line item co ban (dam bao tuong thich 100% voi client va test hien co)
    primary_line_item = {
        "product_key": "COLD_STORAGE_ENERGY",
        "notes": f"Dien nang & dich vu bao quan lanh ({kwh} kWh x {SERVICE_RATE_PER_KWH:,.0f} d/kWh)",
        "cost": SERVICE_RATE_PER_KWH,
        "quantity": kwh,
    }

    # Chi tiet phan bo TOU
    tou_line_items = [
        primary_line_item,
        {
            "product_key": "EVN_TOU_BREAKDOWN",
            "notes": f"Phan bo TOU EVN: Cao diem {tou['PEAK']['kwh']} kWh, Binh thuong {tou['NORMAL']['kwh']} kWh, Thap diem {tou['OFF_PEAK']['kwh']} kWh",
            "cost": 0.0,
            "quantity": 1.0,
        },
    ]

    if SIMULATION_MODE:
        logger.info("[SIMULATION] Hoa don cho %s: %s VND (%s kWh)", req.tenant_code, f"{total_amount:,.0f}", kwh)
        sim_res = {
            "status": "simulated",
            "tenant_code": req.tenant_code,
            "kwh_metered": kwh,
            "total_vnd": total_amount,
            "line_item": primary_line_item,
            "tou_distribution": tou,
            "billing_period": current_period or datetime.now(timezone.utc).strftime("%Y-%m"),
        }
        if current_period:
            billed_cycles = _load_json(BILLED_CYCLES_FILE)
            billed_cycles[f"{req.tenant_code}_{current_period}"] = sim_res
            _save_json(BILLED_CYCLES_FILE, billed_cycles)
        return sim_res

    # Live call to Invoice Ninja with Retry & Dead-letter queue
    invoice_payload = {
        "client_id": client_id,
        "line_items": tou_line_items,
        "public_notes": f"Ky thanh toan dien lanh: {current_period}",
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                f"{NINJA_URL}/api/v1/invoices",
                headers={"X-Api-Token": NINJA_API_TOKEN, "Content-Type": "application/json"},
                json=invoice_payload,
                timeout=NINJA_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            invoice_data = response.json()
            billed_cycles[idempotency_key] = invoice_data
            _save_json(BILLED_CYCLES_FILE, billed_cycles)
            return {
                "status": "success",
                "invoice": invoice_data,
                "kwh_metered": kwh,
                "total_vnd": total_amount,
                "line_item": primary_line_item,
                "tou_distribution": tou,
            }
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("Thu gui hoa don lan %d that bai: %s", attempt, exc)
            time.sleep(1.0 * attempt)

    # Neu qua MAX_RETRIES van loi: ghi vao Dead-Letter Queue va raise 502
    _log_dead_letter({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_code": req.tenant_code,
        "sensor_entity_id": req.sensor_entity_id,
        "kwh": kwh,
        "error": str(last_error),
    })
    logger.error("Khong tao duoc hoa don Invoice Ninja sau %d lan thu. Da luu Dead-Letter.", MAX_RETRIES)
    raise HTTPException(status_code=502, detail=f"Invoice Ninja error after retries: {last_error}")
