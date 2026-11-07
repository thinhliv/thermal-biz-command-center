"""
Connector A: ThingsBoard Alarm -> ERPNext Asset Repair Bridge

Nhan webhook Alarm tu ThingsBoard Rule Engine va tao phieu sua chua tai san
(Asset Repair) trong ERPNext, kem dong vat tu gas lanh R404A du kien tieu hao.

Contract ERPNext duoc doi chieu truc tiep voi frappe/erpnext@version-15:
  - Doctype dung la "Asset Repair" (module Assets). ERPNext KHONG co doctype
    "Maintenance Request" - do la doctype cua Odoo. Goi sang doctype khong ton tai
    thi /api/resource tra 404, tuc moi alarm deu that bai.
  - Field bat buoc: naming_series (Select, chi mot lua chon ACC-ASR-.YYYY.-),
    failure_date (Datetime), asset (Link -> Asset).
  - Vat tu tieu hao nam trong bang con "stock_items" (Asset Repair Consumed Item);
    item_code va warehouse bat buoc o dong con, consumed_quantity la kieu Data (chuoi).
  - KHONG dung Stock Reservation Entry: voucher_type cua no la Select chi cho phep
    "Sales Order", nen ve mat du lieu khong the treo vao mot phieu sua chua.

Bao mat:
  - Moi request phai mang header X-Connector-API-Key khop CONNECTOR_API_KEY.
  - Asset ERPNext lay tu DEVICE_ASSET_MAP (cau hinh phia server). Nguoi goi khong tu
    khai duoc asset, neu khong ho co the tao phieu len tai san cua don vi khac.
  - Ket noi ERPNext chi chay khi co du cap API key/secret that; muon chay thu thi
    bat SIMULATION_MODE=true mot cach tuong minh.
"""

import hmac
import json
import logging
import os
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TB_ERPNext_Bridge")

STATE_DIR = Path(os.getenv("CONNECTOR_STATE_DIR") or (Path(__file__).resolve().parent / "data"))
COOLDOWN_FILE = STATE_DIR / "alarm_cooldown.json"

ERPNEXT_URL = os.getenv("ERPNEXT_URL", "").rstrip("/")
ERPNEXT_API_KEY = os.getenv("ERPNEXT_API_KEY", "")
ERPNEXT_API_SECRET = os.getenv("ERPNEXT_API_SECRET", "")
CONNECTOR_API_KEY = os.getenv("CONNECTOR_API_KEY", "")
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").strip().lower() == "true"

ERPNEXT_COMPANY = os.getenv("ERPNEXT_COMPANY", "")
ERPNEXT_WAREHOUSE = os.getenv("ERPNEXT_STORE_WAREHOUSE", "")
ASSET_REPAIR_NAMING_SERIES = os.getenv("ERPNEXT_ASSET_REPAIR_NAMING_SERIES", "ACC-ASR-.YYYY.-")
REFRIGERANT_ITEM_CODE = os.getenv("REFRIGERANT_ITEM_CODE", "R404A-GAS-CYLINDER")
REFRIGERANT_RESERVE_QTY = float(os.getenv("REFRIGERANT_RESERVE_QTY", "2"))

VALID_SEVERITIES = {"CRITICAL", "MAJOR", "WARNING", "INFO"}
HIGH_PRIORITY_SEVERITIES = {"CRITICAL", "MAJOR"}
REFRIGERANT_KEYWORDS = (
    "COP",
    "THERMAL",
    "OVERHEAT",
    "REFRIGERANT",
    "COMPRESSOR",
    "HIGH_PRESSURE",
)
REQUEST_TIMEOUT_SECONDS = 10
ALARM_COOLDOWN_SECONDS = int(os.getenv("ALARM_COOLDOWN_SECONDS", "300"))

#: Frappe bao loi du lieu/phan quyen bang 400/403/404/417. Retry khong giup ich, nen dich
#: thanh 422 de nguoi goi biet day la loi contract chu khong phai loi mang tam thoi.
_ERPNEXT_CLIENT_ERRORS = {400, 403, 404, 417}


def load_device_asset_map() -> Dict[str, str]:
    raw = os.getenv("DEVICE_ASSET_MAP", "{}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DEVICE_ASSET_MAP is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("DEVICE_ASSET_MAP must be a JSON object of device_name -> asset_name")
    return {str(k): str(v) for k, v in parsed.items()}


DEVICE_ASSET_MAP = load_device_asset_map()


class ThingsBoardAlarmPayload(BaseModel):
    alarm_id: Optional[str] = None
    device_name: str = Field(min_length=1, max_length=200)
    alarm_type: str = Field(min_length=1, max_length=100)
    severity: str = Field(min_length=1, max_length=20)
    details: Dict[str, Any] = Field(default_factory=dict)
    #: Thoi diem su co that (ThingsBoard gui epoch ms). Thieu thi lay luc nhan webhook.
    start_ts: Optional[int] = Field(default=None, ge=0)

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
    if SIMULATION_MODE:
        return
    if not (ERPNEXT_URL and ERPNEXT_API_KEY and ERPNEXT_API_SECRET):
        raise RuntimeError(
            "ERPNEXT_URL / ERPNEXT_API_KEY / ERPNEXT_API_SECRET are not fully set. "
            "Set them, or start with SIMULATION_MODE=true explicitly."
        )
    if not DEVICE_ASSET_MAP:
        raise RuntimeError(
            "DEVICE_ASSET_MAP is empty. Asset Repair bat buoc co `asset` hop le, nen phai "
            "anh xa device_name cua ThingsBoard sang ten Asset trong ERPNext."
        )
    if not REFRIGERANT_RESERVE_QTY > 0:
        raise RuntimeError("REFRIGERANT_RESERVE_QTY must be greater than 0.")


validate_config()


# --------------------------------------------------------------------------- #
# Cooldown ben vung (file): khong mat khi restart, dung chung giua cac worker
# --------------------------------------------------------------------------- #
def _read_cooldowns() -> Dict[str, float]:
    try:
        with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.error("Khong doc duoc %s: %s", COOLDOWN_FILE, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): float(v) for k, v in data.items()}


def _write_cooldowns(cooldowns: Dict[str, float]) -> bool:
    """Ghi nguyen tu (file tam + rename) de khong hong state khi container bi giet giua chung."""
    handle = None
    tmp_name = None
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(dir=str(STATE_DIR), suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(cooldowns, f)
        handle = None  # os.fdopen da so huu va dong fd
        os.replace(tmp_name, COOLDOWN_FILE)
        return True
    except OSError as exc:
        logger.error("Khong ghi duoc %s: %s", COOLDOWN_FILE, exc)
        return False
    finally:
        if handle is not None:
            os.close(handle)
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)


def is_in_cooldown(alarm_id: Optional[str]) -> bool:
    if not alarm_id:
        return False

    now = time.time()
    fresh = {
        key: ts
        for key, ts in _read_cooldowns().items()
        if now - ts <= ALARM_COOLDOWN_SECONDS
    }

    if alarm_id in fresh:
        return True

    fresh[alarm_id] = now
    # Fail-open: khong ghi duoc state thi van xu ly alarm. Bo lot mot canh bao su co
    # nghiem trong thiet hai hon nhieu so voi kha nang tao ra mot phieu sua chua trung.
    _write_cooldowns(fresh)
    return False


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Connector A ready (simulation_mode=%s, cooldown=%ds, device_map=%d, asset_series=%s)",
        SIMULATION_MODE,
        ALARM_COOLDOWN_SECONDS,
        len(DEVICE_ASSET_MAP),
        ASSET_REPAIR_NAMING_SERIES,
    )
    if not SIMULATION_MODE and not ERPNEXT_WAREHOUSE:
        logger.warning(
            "ERPNEXT_STORE_WAREHOUSE rong: Asset Repair se khong giu duoc vat tu R404A "
            "vi dong stock_items bat buoc co warehouse."
        )
    yield


app = FastAPI(
    title="ThingsBoard to ERPNext Asset Repair Bridge",
    description=(
        "Captures IoT thermal alarms from ThingsBoard and creates ERPNext Asset Repair "
        "documents with R404A refrigerant consumption lines"
    ),
    lifespan=lifespan,
)


def require_api_key(x_connector_api_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_connector_api_key, CONNECTOR_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid connector API key")


def resolve_asset_name(device_name: str) -> str:
    asset = DEVICE_ASSET_MAP.get(device_name)
    if asset:
        return asset
    if SIMULATION_MODE:
        return device_name
    raise HTTPException(
        status_code=422,
        detail=(
            f"device_name '{device_name}' chua duoc anh xa sang Asset trong ERPNext "
            "(DEVICE_ASSET_MAP). Tu choi tao phieu vi Asset Repair bat buoc co asset hop le."
        ),
    )


def failure_datetime(payload: ThingsBoardAlarmPayload) -> datetime:
    if payload.start_ts:
        return datetime.fromtimestamp(payload.start_ts / 1000, tz=timezone.utc)
    return datetime.now(timezone.utc)


def needs_refrigerant(payload: ThingsBoardAlarmPayload) -> bool:
    """Giu gas lanh khi su co lien quan nhiet/ap suat/COP, hoac canh bao muc cao."""
    if payload.severity in HIGH_PRIORITY_SEVERITIES:
        return True
    alarm_type = payload.alarm_type.upper()
    return any(keyword in alarm_type for keyword in REFRIGERANT_KEYWORDS)


def build_stock_items(payload: ThingsBoardAlarmPayload) -> List[Dict[str, Any]]:
    if not needs_refrigerant(payload):
        return []
    return [
        {
            "item_code": REFRIGERANT_ITEM_CODE,
            "warehouse": ERPNEXT_WAREHOUSE,
            "consumed_quantity": f"{REFRIGERANT_RESERVE_QTY:g}",
        }
    ]


def build_asset_repair(payload: ThingsBoardAlarmPayload, asset_name: str) -> Dict[str, Any]:
    occurred = failure_datetime(payload)
    details = json.dumps(payload.details, ensure_ascii=False, sort_keys=True)
    description = (
        "Canh bao tu dong tu ThingsBoard Rule Engine:\n"
        f"- Thiet bi IoT: {payload.device_name}\n"
        f"- Asset ERPNext: {asset_name}\n"
        f"- Loai canh bao: {payload.alarm_type}\n"
        f"- Muc do nghiem trong: {payload.severity}\n"
        f"- Thong so ghi nhan: {details}\n"
        "Yeu cau: ky thuat vien kiem tra ap suat, he so COP va nhiet do may."
    )

    stock_items = build_stock_items(payload)
    document: Dict[str, Any] = {
        "doctype": "Asset Repair",
        "naming_series": ASSET_REPAIR_NAMING_SERIES,
        "asset": asset_name,
        # Frappe kieu Datetime: 'YYYY-MM-DD HH:MM:SS'
        "failure_date": occurred.strftime("%Y-%m-%d %H:%M:%S"),
        "repair_status": "Pending",
        "description": description,
        "stock_consumption": 1 if stock_items else 0,
        "stock_items": stock_items,
    }
    if ERPNEXT_COMPANY:
        document["company"] = ERPNEXT_COMPANY
    return document


def refrigerant_hold(payload: ThingsBoardAlarmPayload, asset_name: str) -> Optional[Dict[str, Any]]:
    """Mo ta dong giu vat tu de nguoi goi theo doi duoc.

    Nam trong stock_items cua Asset Repair, khong phai mot Stock Reservation Entry rieng:
    ERPNext chi cho phep reservation treo theo Sales Order.
    """
    stock_items = build_stock_items(payload)
    if not stock_items:
        return None
    return {
        "item_code": stock_items[0]["item_code"],
        "warehouse": stock_items[0]["warehouse"],
        "reserved_qty": REFRIGERANT_RESERVE_QTY,
        "asset": asset_name,
        "alarm_id": payload.alarm_id,
        "attached_to": "Asset Repair.stock_items",
        # Trung thuc ve nghiep vu: vat tu chi thuc su xuat kho khi Asset Repair duoc submit.
        "status": "pending_repair_submit",
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "thingsboard-erpnext-bridge",
        "simulation_mode": SIMULATION_MODE,
        "target_doctype": "Asset Repair",
        "mapped_devices": len(DEVICE_ASSET_MAP),
        "warehouse_configured": bool(ERPNEXT_WAREHOUSE),
        "active_cooldowns": len(_read_cooldowns()),
    }


def _erpnext_error_detail(response: requests.Response) -> str:
    """Loi Frappe thuong nam trong _server_messages (JSON long trong JSON). Boc ra de de chan benh."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if not isinstance(body, dict):
        return json.dumps(body)[:500]

    raw_messages = body.get("_server_messages")
    if raw_messages:
        try:
            parsed = json.loads(raw_messages)
        except (ValueError, TypeError):
            return str(raw_messages)[:500]
        texts = [
            m.get("message")
            for m in parsed
            if isinstance(m, dict) and m.get("message")
        ]
        if texts:
            return "; ".join(str(t) for t in texts)[:500]

    for key in ("exc", "error", "message"):
        if body.get(key):
            return str(body[key])[:500]
    return json.dumps(body, ensure_ascii=False)[:500]


def create_asset_repair(document: Dict[str, Any]) -> Dict[str, Any]:
    try:
        response = requests.post(
            f"{ERPNEXT_URL}/api/resource/Asset Repair",
            json=document,
            headers={
                "Authorization": f"token {ERPNEXT_API_KEY}:{ERPNEXT_API_SECRET}",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.error("Khong ket noi duoc ERPNext: %s", exc)
        raise HTTPException(status_code=502, detail=f"ERPNext integration error: {exc}") from exc

    if response.status_code >= 400:
        detail = _erpnext_error_detail(response)
        status_code = 422 if response.status_code in _ERPNEXT_CLIENT_ERRORS else 502
        logger.error("ERPNext tu choi Asset Repair (%d): %s", response.status_code, detail)
        raise HTTPException(
            status_code=status_code, detail=f"ERPNext rejected Asset Repair: {detail}"
        )

    return response.json()


@app.post("/webhook/thingsboard-alarm", dependencies=[Depends(require_api_key)])
def handle_thingsboard_alarm(payload: ThingsBoardAlarmPayload) -> Dict[str, Any]:
    logger.info(
        "Alarm tu ThingsBoard: %s - %s [%s] (id=%s)",
        payload.device_name,
        payload.alarm_type,
        payload.severity,
        payload.alarm_id,
    )

    if is_in_cooldown(payload.alarm_id):
        logger.info("Alarm %s dang trong thoi gian cooldown, bo qua khong tao duplicate.", payload.alarm_id)
        return {
            "status": "cooldown_suppressed",
            "alarm_id": payload.alarm_id,
            "message": "Alarm is within cooldown window",
        }

    asset_name = resolve_asset_name(payload.device_name)
    asset_repair = build_asset_repair(payload, asset_name)
    hold = refrigerant_hold(payload, asset_name)

    if SIMULATION_MODE:
        logger.info(
            "[SIMULATION] Asset Repair cho asset %s (%d dong vat tu)",
            asset_name,
            len(asset_repair["stock_items"]),
        )
        return {
            "status": "simulated",
            "data": asset_repair,
            "asset_repair": asset_repair,
            "refrigerant_hold": hold,
        }

    created = create_asset_repair(asset_repair)
    logger.info("Da tao Asset Repair tren ERPNext cho asset %s", asset_name)
    return {
        "status": "success",
        "erpnext_response": created,
        "asset_repair": asset_repair,
        "refrigerant_hold": hold,
    }
