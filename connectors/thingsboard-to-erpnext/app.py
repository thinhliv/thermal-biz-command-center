"""
Connector A: ThingsBoard Alarm -> ERPNext Maintenance Request Bridge

Nhan webhook Alarm tu ThingsBoard Rule Engine va tao phieu bao tri trong ERPNext.

Bao mat:
  - Moi request phai mang header X-Connector-API-Key khop CONNECTOR_API_KEY.
  - Ket noi ERPNext chi chay khi cap API key/secret that; neu muon chay thu thi
    bat SIMULATION_MODE=true mot cach tuong minh (khong con "magic sentinel").
"""

import hmac
import logging
import os
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

VALID_SEVERITIES = {"CRITICAL", "MAJOR", "WARNING", "INFO"}
HIGH_PRIORITY_SEVERITIES = {"CRITICAL", "MAJOR"}
REQUEST_TIMEOUT_SECONDS = 10


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Connector A ready (simulation_mode=%s)", SIMULATION_MODE)
    yield


app = FastAPI(
    title="ThingsBoard to ERPNext Maintenance Bridge",
    description="Captures IoT thermal alarms from ThingsBoard and creates ERPNext maintenance records",
    lifespan=lifespan,
)


def require_api_key(x_connector_api_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_connector_api_key, CONNECTOR_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid connector API key")


def build_issue(payload: ThingsBoardAlarmPayload) -> Dict[str, Any]:
    subject = f"[IoT Alert] {payload.alarm_type} tren thiet bi {payload.device_name}"
    description = (
        "Canh bao tu dong tu ThingsBoard Rule Engine:\n"
        f"- Thiet bi: {payload.device_name}\n"
        f"- Muc do nghiem trong: {payload.severity}\n"
        f"- Chi tiet thong so: {payload.details}\n"
        "Hanh dong yeu cau: Ky thuat vien kiem tra ap suat, he so COP va nhiet do may."
    )
    return {
        "doctype": "Issue",
        "subject": subject,
        "raised_by": "iot-thingsboard@system.local",
        "description": description,
        "priority": "High" if payload.severity in HIGH_PRIORITY_SEVERITIES else "Medium",
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "thingsboard-erpnext-bridge",
        "simulation_mode": SIMULATION_MODE,
    }


@app.post("/webhook/thingsboard-alarm", dependencies=[Depends(require_api_key)])
def handle_thingsboard_alarm(payload: ThingsBoardAlarmPayload) -> Dict[str, Any]:
    logger.info(
        "Alarm tu ThingsBoard: %s - %s [%s]",
        payload.device_name,
        payload.alarm_type,
        payload.severity,
    )
    erpnext_payload = build_issue(payload)

    if SIMULATION_MODE:
        logger.info("[SIMULATION] %s", erpnext_payload["subject"])
        return {"status": "simulated", "data": erpnext_payload}

    try:
        response = requests.post(
            f"{ERPNEXT_URL}/api/resource/{erpnext_payload['doctype']}",
            json=erpnext_payload,
            headers={
                "Authorization": f"token {ERPNEXT_API_KEY}:{ERPNEXT_API_SECRET}",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Khong gui duoc phieu sang ERPNext: %s", exc)
        raise HTTPException(status_code=502, detail=f"ERPNext integration error: {exc}") from exc

    created = response.json()
    logger.info("Da tao ERPNext record: %s", created)
    return {"status": "success", "erpnext_response": created}
