"""
Connector A: ThingsBoard Alarm -> ERPNext Maintenance Request & Stock Reservation Bridge

Nhan webhook Alarm tu ThingsBoard Rule Engine va:
  1. Tao phieu bao tri (Maintenance Request) trong ERPNext kem field asset.
  2. Tu dong khoa kho (Stock Reservation) 2 binh gas lanh R404A khi phat hien su co nhiet/ap suat/COP.
  3. Cooldown va idempotency theo alarm_id de chong spam phieu bao tri.

Bao mat:
  - Moi request phai mang header X-Connector-API-Key khop CONNECTOR_API_KEY.
  - Ket noi ERPNext chi chay khi co cap API key/secret that; neu muon chay thu thi
    bat SIMULATION_MODE=true mot cach tuong minh.
"""

import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TB_ERPNext_Bridge")

ERPNEXT_URL = os.getenv("ERPNEXT_URL", "").rstrip("/")
ERPNEXT_API_KEY = os.getenv("ERPNEXT_API_KEY", "")
ERPNEXT_API_SECRET = os.getenv("ERPNEXT_API_SECRET", "")
CONNECTOR_API_KEY = os.getenv("CONNECTOR_API_KEY", "")
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").strip().lower() == "true"
ERPNEXT_COMPANY = os.getenv("ERPNEXT_COMPANY", "ThermalBiz ESCO")
ERPNEXT_WAREHOUSE = os.getenv("ERPNEXT_STORE_WAREHOUSE", "Kho Vat Tu - TB")

VALID_SEVERITIES = {"CRITICAL", "MAJOR", "WARNING", "INFO"}
HIGH_PRIORITY_SEVERITIES = {"CRITICAL", "MAJOR"}
REQUEST_TIMEOUT_SECONDS = 10
ALARM_COOLDOWN_SECONDS = int(os.getenv("ALARM_COOLDOWN_SECONDS", "300"))

# Idempotency / Cooldown cache: alarm_id -> timestamp
_alarm_cooldown_cache: Dict[str, float] = {}


class ThingsBoardAlarmPayload(BaseModel):
    alarm_id: Optional[str] = None
    device_name: str = Field(min_length=1, max_length=200)
    alarm_type: str = Field(min_length=1, max_length=100)
    severity: str = Field(min_length=1, max_length=20)
    details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("severity")
    @classmethod
    def severity_must_be_known(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(VALID_SEVERITIES)}")
        return normalized


def validate_config() -> None:
    if not CONNECTOR_API_KEY:
        raise RuntimeError(
            "CONNECTOR_API_KEY is not set. Refusing to start an unauthenticated alarm webhook."
        )
    if not SIMULATION_MODE and not (ERPNEXT_URL and ERPNEXT_API_KEY and ERPNEXT_API_SECRET):
        raise RuntimeError(
            "ERPNEXT_URL / ERPNEXT_API_KEY / ERPNEXT_API_SECRET are not fully set. "
            "Set them, or start with SIMULATION_MODE=true explicitly."
        )


validate_config()


def is_in_cooldown(alarm_id: Optional[str]) -> bool:
    if not alarm_id:
        return False
    now = time.time()
    # Don dep cache cu
    expired = [k for k, ts in _alarm_cooldown_cache.items() if now - ts > ALARM_COOLDOWN_SECONDS]
    for k in expired:
        _alarm_cooldown_cache.pop(k, None)

    if alarm_id in _alarm_cooldown_cache:
        return True
    _alarm_cooldown_cache[alarm_id] = now
    return False


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Connector A ready (simulation_mode=%s, cooldown=%ds)", SIMULATION_MODE, ALARM_COOLDOWN_SECONDS)
    yield


app = FastAPI(
    title="ThingsBoard to ERPNext Maintenance Bridge",
    description="Captures IoT thermal alarms from ThingsBoard and creates ERPNext Maintenance Requests with R404A stock reservations",
    lifespan=lifespan,
)


def require_api_key(x_connector_api_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_connector_api_key, CONNECTOR_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid connector API key")


def build_maintenance_request(payload: ThingsBoardAlarmPayload) -> Dict[str, Any]:
    subject = f"[IoT Alert] {payload.alarm_type} tren thiet bi {payload.device_name}"
    description = (
        "Canh bao tu dong tu ThingsBoard Rule Engine:\n"
        f"- Thiet bi / Asset: {payload.device_name}\n"
        f"- Muc do nghiem trong: {payload.severity}\n"
        f"- Chi tiet thong so: {payload.details}\n"
        "Hanh dong yeu cau: Ky thuat vien kiem tra ap suat, he so COP va nhiet do may."
    )
    return {
        "doctype": "Maintenance Request",
        "naming_series": "MAT-MR-.YYYY.-",
        "maintenance_type": "Unscheduled",
        "company": ERPNEXT_COMPANY,
        "customer": "Noi bo",
        "asset": payload.device_name,
        "item_name": payload.device_name,
        "contact_person": "IoT Operations",
        "status": "Draft",
        "description": description,
        "purposes": [
            {
                "item_code": payload.device_name,
                "item_name": payload.device_name,
                "work_summary": subject,
                "maintenance_type": "Unscheduled",
            }
        ],
    }


def build_r404a_stock_reservation(payload: ThingsBoardAlarmPayload) -> Optional[Dict[str, Any]]:
    # Khoa kho gas lanh R404A khi co su co COP giam, qua nhiet, hoac canh bao muc CRITICAL/MAJOR
    needs_refrigerant = (
        payload.severity in HIGH_PRIORITY_SEVERITIES
        or any(k in payload.alarm_type.upper() for k in ["COP", "THERMAL", "OVERHEAT", "REFRIGERANT", "COMPRESSOR"])
    )
    if not needs_refrigerant:
        return None

    return {
        "doctype": "Stock Reservation Entry",
        "voucher_type": "Maintenance Request",
        "item_code": "R404A-GAS-CYLINDER",
        "warehouse": ERPNEXT_WAREHOUSE,
        "reserved_qty": 2.0,
        "voucher_detail_no": payload.alarm_id or "ALM-AUTO",
        "description": f"Tu dong khoa 2 binh gas R404A du phong cho su co {payload.alarm_type} tai {payload.device_name}",
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "thingsboard-erpnext-bridge",
        "simulation_mode": SIMULATION_MODE,
        "active_cooldowns": len(_alarm_cooldown_cache),
    }


@app.post("/webhook/thingsboard-alarm", dependencies=[Depends(require_api_key)])
def handle_thingsboard_alarm(payload: ThingsBoardAlarmPayload) -> Dict[str, Any]:
    logger.info(
        "Alarm tu ThingsBoard: %s - %s [%s] (id=%s)",
        payload.device_name,
        payload.alarm_type,
        payload.severity,
        payload.alarm_id,
    )

    if payload.alarm_id and is_in_cooldown(payload.alarm_id):
        logger.info("Alarm %s dang trong thoi gian cooldown, bo qua khong tao duplicate.", payload.alarm_id)
        return {
            "status": "cooldown_suppressed",
            "alarm_id": payload.alarm_id,
            "message": "Alarm is within cooldown window",
        }

    maint_req = build_maintenance_request(payload)
    stock_hold = build_r404a_stock_reservation(payload)

    if SIMULATION_MODE:
        logger.info("[SIMULATION] Maintenance Request: %s (Asset: %s)", maint_req["doctype"], maint_req["asset"])
        if stock_hold:
            logger.info("[SIMULATION] Stock Hold: 2x %s tai %s", stock_hold["item_code"], stock_hold["warehouse"])
        return {
            "status": "simulated",
            "data": maint_req,
            "maintenance_request": maint_req,
            "stock_reservation": stock_hold,
        }

    # Live ERPNext execution
    headers = {
        "Authorization": f"token {ERPNEXT_API_KEY}:{ERPNEXT_API_SECRET}",
        "Content-Type": "application/json",
    }
    try:
        # 1. Tao Maintenance Request
        resp_maint = requests.post(
            f"{ERPNEXT_URL}/api/resource/Maintenance Request",
            json=maint_req,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp_maint.raise_for_status()
        created_maint = resp_maint.json()

        # 2. Khoa kho R404A neu can
        created_stock = None
        if stock_hold:
            try:
                resp_stock = requests.post(
                    f"{ERPNEXT_URL}/api/resource/Stock Reservation Entry",
                    json=stock_hold,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if resp_stock.ok:
                    created_stock = resp_stock.json()
            except Exception as stock_err:
                logger.warning("Khong the khoa kho R404A tren ERPNext: %s", stock_err)

    except requests.RequestException as exc:
        logger.error("Khong gui duoc phieu sang ERPNext: %s", exc)
        raise HTTPException(status_code=502, detail=f"ERPNext integration error: {exc}") from exc

    return {
        "status": "success",
        "erpnext_response": created_maint,
        "stock_reservation": created_stock,
    }
