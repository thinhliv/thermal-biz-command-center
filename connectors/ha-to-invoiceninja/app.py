"""
Connector B: Home Assistant Metering -> Invoice Ninja Usage Billing Bridge

Doc so kWh tu Home Assistant va tao hoa don trong Invoice Ninja.

Bao mat & toan ven du lieu:
  - Moi request phai mang header X-Connector-API-Key khop CONNECTOR_API_KEY.
  - client_id cua Invoice Ninja KHONG do nguoi goi tu khai; no duoc suy ra tu
    tenant_code qua bang anh xa TENANT_CLIENT_MAP nam phia server.
  - Don gia dich vu nam phia server (SERVICE_RATE_PER_KWH), khong nhan tu request.
  - Khi khong doc duoc Home Assistant, yeu cau THAT BAI (503). Khong bao gio
    xuat hoa don dua tren so lieu gia lap.
"""

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("HA_InvoiceNinja_Bridge")

HASS_URL = os.getenv("HASS_URL", "").rstrip("/")
HASS_TOKEN = os.getenv("HASS_TOKEN", "")
NINJA_URL = os.getenv("INVOICE_NINJA_URL", "").rstrip("/")
NINJA_API_TOKEN = os.getenv("INVOICE_NINJA_TOKEN", "")
CONNECTOR_API_KEY = os.getenv("CONNECTOR_API_KEY", "")
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").strip().lower() == "true"

SERVICE_RATE_PER_KWH = float(os.getenv("SERVICE_RATE_PER_KWH", "3500"))
HA_TIMEOUT_SECONDS = 5
NINJA_TIMEOUT_SECONDS = 10


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
    sensor_entity_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9_]+\.[a-z0-9_]+$")


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
    description="Usage-based billing from Home Assistant power meters into Invoice Ninja",
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


def read_meter(entity_id: str) -> float:
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


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "ha-invoiceninja-bridge",
        "simulation_mode": SIMULATION_MODE,
    }


@app.post("/api/generate-invoice", dependencies=[Depends(require_api_key)])
def generate_usage_invoice(req: BillingTriggerRequest) -> Dict[str, Any]:
    client_id = resolve_client_id(req.tenant_code)
    logger.info("Sinh hoa don cho tenant %s (client %s), sensor %s", req.tenant_code, client_id, req.sensor_entity_id)

    kwh = read_meter(req.sensor_entity_id) if not SIMULATION_MODE else 1250.0
    total_amount = kwh * SERVICE_RATE_PER_KWH
    line_item = {
        "product_key": "COLD_STORAGE_ENERGY",
        "notes": f"Dien nang & dich vu bao quan lanh ({kwh} kWh x {SERVICE_RATE_PER_KWH:,.0f} d/kWh)",
        "cost": SERVICE_RATE_PER_KWH,
        "quantity": kwh,
    }

    if SIMULATION_MODE:
        logger.info("[SIMULATION] Hoa don cho %s: %s VND", req.tenant_code, f"{total_amount:,.0f}")
        return {
            "status": "simulated",
            "tenant_code": req.tenant_code,
            "kwh_metered": kwh,
            "total_vnd": total_amount,
            "line_item": line_item,
        }

    try:
        response = requests.post(
            f"{NINJA_URL}/api/v1/invoices",
            headers={"X-Api-Token": NINJA_API_TOKEN, "Content-Type": "application/json"},
            json={"client_id": client_id, "line_items": [line_item]},
            timeout=NINJA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Khong tao duoc hoa don Invoice Ninja: %s", exc)
        raise HTTPException(status_code=502, detail=f"Invoice Ninja error: {exc}") from exc

    return {"status": "success", "invoice": response.json()}
