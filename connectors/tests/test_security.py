"""
Kiem chung bao mat VA nghiep vu cua 2 connector.

Diem khac biet lon nhat so voi ban cu: ban cu chi chay SIMULATION_MODE, nen toan bo
duong goi ERPNext / Home Assistant / backend / Invoice Ninja that KHONG duoc test.
Do la ly do nhung loi sau day da "xanh" ma van hong o production:
  - connector A POST sang doctype "Maintenance Request" khong ton tai trong ERPNext
    -> 404 -> 502 cho moi alarm;
  - connector A gui `voucher_type: "Maintenance Request"` cho Stock Reservation Entry,
    trong khi Select do chi cho phep "Sales Order";
  - connector B tinh total = kWh x phi dich vu, KHONG cong tien dien -> that thu;
  - connector B phan bo TOU theo ty le 20/45/35 viet chet, khong phai so do;
  - connector B raise NameError SAU khi Invoice Ninja da tao hoa don -> khach van
    nhan hoa don, nguoi goi thay loi, retry thi thanh xuat hoa don doi.

Vi the o day co mot lop HttpStub: moi test tuy duong thuc thi phai mock het cac
endpoint ben ngoai, va assert tren PAYLOAD THAT SU duoc gui di.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest
import requests as real_requests
from fastapi.testclient import TestClient

CONNECTORS_DIR = Path(__file__).resolve().parents[1]
CONNECTOR_A_PATH = CONNECTORS_DIR / "thingsboard-to-erpnext" / "app.py"
CONNECTOR_B_PATH = CONNECTORS_DIR / "ha-to-invoiceninja" / "app.py"

API_KEY = "test-connector-key"
BACKEND_KEY = "test-backend-connector-key"
TENANT_MAP = {"KHO_DONG_01": "ninja-client-77"}
ASSET_MAP = {"KHO_DONG_01": "ACC-KHO-0001"}

MANAGED_ENV_KEYS = (
    "ERPNEXT_URL", "ERPNEXT_API_KEY", "ERPNEXT_API_SECRET",
    "ERPNEXT_COMPANY", "ERPNEXT_STORE_WAREHOUSE", "ERPNEXT_ASSET_REPAIR_NAMING_SERIES",
    "REFRIGERANT_ITEM_CODE", "REFRIGERANT_RESERVE_QTY", "DEVICE_ASSET_MAP",
    "ALARM_COOLDOWN_SECONDS",
    "HASS_URL", "HASS_TOKEN", "INVOICE_NINJA_URL", "INVOICE_NINJA_TOKEN",
    "BACKEND_URL", "BACKEND_CONNECTOR_API_KEY", "RETRY_BACKOFF_SECONDS",
    "CONNECTOR_API_KEY", "SIMULATION_MODE", "TENANT_CLIENT_MAP", "CONNECTOR_STATE_DIR",
)

ALARM = {
    "alarm_id": "tb-alarm-001",
    "device_name": "KHO_DONG_01",
    "alarm_type": "COP_DROP",
    "severity": "CRITICAL",
    "details": {"cop": 2.9, "window_minutes": 30},
}

METER_BODY = {
    "tenant_code": "KHO_DONG_01",
    "sensor_entity_id": "sensor.kho_dong_01_energy_kwh",
}

ENTITY_ID = "sensor.kho_dong_01_energy_kwh"
HA_STATE_URL = f"/api/states/{ENTITY_ID}"
BACKEND_BILLING_URL = "/api/ingest/billing"
NINJA_INVOICE_URL = "/api/v1/invoices"
EXTERNAL_REF_URL = "/external-reference"

#: Mot hoa don backend that: tien dien > 0, phi dich vu > 0, split tu telemetry.
PRICES = {"PEAK": 4586, "NORMAL": 2824, "OFF_PEAK": 1808}
BANDS = {"PEAK": 100.0, "NORMAL": 225.0, "OFF_PEAK": 175.0}
ELECTRICITY_VND = sum(round(kwh * PRICES[band]) for band, kwh in BANDS.items())
SERVICE_RATE = 3500
TOTAL_KWH = sum(BANDS.values())
SERVICE_VND = int(round(TOTAL_KWH * SERVICE_RATE))


def backend_invoice(**overrides) -> dict:
    invoice = {
        "id": 41,
        "tenant_code": "KHO_DONG_01",
        "period_start": "2026-09-01T00:00:00",
        "period_end": "2026-10-01T00:00:00",
        "total_kwh": TOTAL_KWH,
        "kwh_by_band": dict(BANDS),
        "electricity_vnd": ELECTRICITY_VND,
        "service_fee_vnd": SERVICE_VND,
        "total_vnd": ELECTRICITY_VND + SERVICE_VND,
        "external_invoice_id": None,
        "breakdown": {
            "split_method": "telemetry",
            "prices_vnd_per_kwh": dict(PRICES),
            "reading_start_kwh": 10_000.0,
            "reading_end_kwh": 10_500.0,
            "service_rate_per_kwh": SERVICE_RATE,
            "warnings": [],
        },
        "issued_at": "2026-10-01T02:00:00",
        "duplicated_call": False,
    }
    invoice.update(overrides)
    return invoice


# --------------------------------------------------------------------------- #
# Lop HTTP gia: ghi lai moi call, dinh tuyen theo (method, duoi URL)
# --------------------------------------------------------------------------- #
class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload if payload is not None else {})

    def json(self):
        if self._payload is None:
            raise ValueError("response has no JSON body")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise real_requests.HTTPError(f"HTTP {self.status_code}", response=self)


class HttpStub:
    """Thay the module `requests`. Thuoc tinh loi giu nguyen de `except` that bat duoc."""

    RequestException = real_requests.RequestException
    ConnectionError = real_requests.ConnectionError
    HTTPError = real_requests.HTTPError

    def __init__(self, routes: dict | None = None):
        self.routes = dict(routes or {})
        self.calls: list[tuple[str, str, dict]] = []

    def _send(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        for (route_method, suffix), handler in self.routes.items():
            if method == route_method and url.endswith(suffix):
                return handler(kwargs) if callable(handler) else handler
        raise AssertionError(f"Test chua dinh tuyen cho call nay: {method} {url}")

    def get(self, url, **kwargs):
        return self._send("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._send("POST", url, **kwargs)

    def patch(self, url, **kwargs):
        return self._send("PATCH", url, **kwargs)

    # -- tro giup assert -- #
    def bodies(self, suffix: str) -> list:
        return [kwargs.get("json") for method, url, kwargs in self.calls if url.endswith(suffix)]

    def count(self, suffix: str) -> int:
        return sum(1 for _, url, _ in self.calls if url.endswith(suffix))


def network_error(*_args, **_kwargs):
    raise real_requests.ConnectionError("connection refused")


# --------------------------------------------------------------------------- #
# Nap connector voi bo bien moi truong rieng (config doc luc import)
# --------------------------------------------------------------------------- #
def load_connector(path: Path, module_name: str, env: dict) -> ModuleType:
    sys.modules.pop(module_name, None)
    saved = {key: os.environ.get(key) for key in MANAGED_ENV_KEYS}
    for key in MANAGED_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.update({k: str(v) for k, v in env.items()})
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return module


@pytest.fixture()
def state_dir(tmp_path) -> str:
    """State rieng cho moi test: cooldown / DLQ khong duoc ri sang test khac."""
    return str(tmp_path / "connector-state")


def connector_a(state_dir: str, **overrides) -> ModuleType:
    return load_connector(
        CONNECTOR_A_PATH,
        "connector_a_under_test",
        {
            "CONNECTOR_API_KEY": API_KEY,
            "SIMULATION_MODE": "true",
            "CONNECTOR_STATE_DIR": state_dir,
            "DEVICE_ASSET_MAP": json.dumps(ASSET_MAP),
            "ERPNEXT_STORE_WAREHOUSE": "Kho Vat Tu - TB",
            **overrides,
        },
    )


def live_connector_a(state_dir: str, **overrides) -> ModuleType:
    defaults = {
        "SIMULATION_MODE": "false",
        "ERPNEXT_URL": "http://erpnext.test",
        "ERPNEXT_API_KEY": "erp-key",
        "ERPNEXT_API_SECRET": "erp-secret",
        "ERPNEXT_COMPANY": "ThermalBiz ESCO",
    }
    defaults.update(overrides)
    return connector_a(state_dir, **defaults)


def connector_b(state_dir: str, **overrides) -> ModuleType:
    return load_connector(
        CONNECTOR_B_PATH,
        "connector_b_under_test",
        {
            "CONNECTOR_API_KEY": API_KEY,
            "SIMULATION_MODE": "true",
            "CONNECTOR_STATE_DIR": state_dir,
            "TENANT_CLIENT_MAP": json.dumps(TENANT_MAP),
            "RETRY_BACKOFF_SECONDS": "0",
            **overrides,
        },
    )


def live_connector_b(state_dir: str, **overrides) -> ModuleType:
    defaults = {
        "SIMULATION_MODE": "false",
        "HASS_URL": "http://ha.test",
        "HASS_TOKEN": "ha-token",
        "BACKEND_URL": "http://backend.test",
        "BACKEND_CONNECTOR_API_KEY": BACKEND_KEY,
        "INVOICE_NINJA_URL": "http://ninja.test",
        "INVOICE_NINJA_TOKEN": "ninja-token",
    }
    defaults.update(overrides)
    return connector_b(state_dir, **defaults)


def _as_response(value, default_payload):
    if isinstance(value, FakeResponse):
        return value
    return FakeResponse(200, default_payload if value is None else value)


def live_b_routes(
    cumulative: float = 10_500.0,
    invoice: dict | None = None,
    ninja_response=None,
    patch_response=None,
) -> dict:
    return {
        ("GET", HA_STATE_URL): FakeResponse(200, {"state": str(cumulative)}),
        ("POST", BACKEND_BILLING_URL): _as_response(invoice, backend_invoice()),
        ("POST", NINJA_INVOICE_URL): _as_response(ninja_response, {"data": {"id": "INV-9"}}),
        ("PATCH", EXTERNAL_REF_URL): _as_response(patch_response, {"status": "linked"}),
    }


def auth_headers() -> dict:
    return {"X-Connector-API-Key": API_KEY}


def dead_letters(module: ModuleType) -> list[dict]:
    path = Path(module.DEAD_LETTER_FILE)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# =========================================================================== #
# Connector A - bao mat
# =========================================================================== #
def test_a_refuses_to_start_without_api_key(state_dir):
    with pytest.raises(RuntimeError, match="CONNECTOR_API_KEY"):
        connector_a(state_dir, CONNECTOR_API_KEY="")


def test_a_refuses_to_start_without_device_asset_map(state_dir):
    """Khong co anh xa device -> Asset ERPNext thi Asset Repair chac chan bi tu choi.

    Bao loi luc khoi dong hon la de moi alarm deu that bai luc 3h sang.
    """
    with pytest.raises(RuntimeError, match="DEVICE_ASSET_MAP"):
        live_connector_a(state_dir, DEVICE_ASSET_MAP="{}")


def test_a_rejects_missing_api_key(state_dir):
    with TestClient(connector_a(state_dir).app) as client:
        assert client.post("/webhook/thingsboard-alarm", json=ALARM).status_code == 401


def test_a_rejects_wrong_api_key(state_dir):
    with TestClient(connector_a(state_dir).app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json=ALARM, headers={"X-Connector-API-Key": "wrong-key"}
        )
    assert response.status_code == 401


def test_a_rejects_partial_api_key(state_dir):
    """compare_digest, khong phai startswith."""
    with TestClient(connector_a(state_dir).app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json=ALARM, headers={"X-Connector-API-Key": API_KEY[:-1]}
        )
    assert response.status_code == 401


def test_a_accepts_valid_api_key(state_dir):
    with TestClient(connector_a(state_dir).app) as client:
        response = client.post("/webhook/thingsboard-alarm", json=ALARM, headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "simulated"


def test_a_health_is_public(state_dir):
    with TestClient(connector_a(state_dir).app) as client:
        body = client.get("/health").json()
    assert body["target_doctype"] == "Asset Repair"


def test_a_rejects_unknown_severity(state_dir):
    with TestClient(connector_a(state_dir).app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "severity": "APOCALYPTIC"}, headers=auth_headers()
        )
    assert response.status_code == 422


# =========================================================================== #
# Connector A - contract ERPNext (duong that, truoc day KHONG duoc test)
# =========================================================================== #
def test_a_creates_asset_repair_with_r404a_consumption_line(state_dir):
    with TestClient(connector_a(state_dir).app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm",
            json={**ALARM, "alarm_id": "unique-alarm-123"},
            headers=auth_headers(),
        )
    assert response.status_code == 200
    repair = response.json()["asset_repair"]

    assert repair["doctype"] == "Asset Repair"
    assert repair["naming_series"] == "ACC-ASR-.YYYY.-"
    assert repair["repair_status"] == "Pending"
    assert repair["stock_consumption"] == 1

    hold = response.json()["refrigerant_hold"]
    assert hold["item_code"] == "R404A-GAS-CYLINDER"
    assert hold["reserved_qty"] == 2.0
    assert hold["attached_to"] == "Asset Repair.stock_items"


def test_a_uses_mapped_asset_never_the_caller_value(state_dir):
    """Asset lay tu DEVICE_ASSET_MAP phia server.

    Neu de nguoi goi tu khai, ho co the tao phieu sua chua len tai san cua don vi khac.
    """
    with TestClient(connector_a(state_dir).app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm",
            json={**ALARM, "asset": "ACC-CUA-NGUOI-KHAC", "alarm_id": "asset-map-1"},
            headers=auth_headers(),
        )
    assert response.json()["asset_repair"]["asset"] == "ACC-KHO-0001"
    assert "ACC-CUA-NGUOI-KHAC" not in response.text


def test_a_unmapped_device_is_rejected_not_guessed(state_dir):
    mod = live_connector_a(state_dir)
    stub = HttpStub({("POST", "/api/resource/Asset Repair"): FakeResponse(200, {"data": {}})})
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm",
            json={**ALARM, "device_name": "KHO_LA", "alarm_id": "unmapped-1"},
            headers=auth_headers(),
        )

    assert response.status_code == 422
    assert stub.calls == []


def test_a_live_posts_to_asset_repair_only(state_dir):
    """Hoi sinh loi cu: goi sang doctype khong ton tai va tao Stock Reservation Entry vo hieu."""
    mod = live_connector_a(state_dir)
    stub = HttpStub({("POST", "/api/resource/Asset Repair"): FakeResponse(201, {"data": {"name": "ACC-ASR-2026-00001"}})})
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "live-1"}, headers=auth_headers()
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert [url for _, url, _ in stub.calls] == ["http://erpnext.test/api/resource/Asset Repair"]

    document = stub.bodies("/api/resource/Asset Repair")[0]
    assert document["doctype"] == "Asset Repair"
    assert document["asset"] == "ACC-KHO-0001"
    assert document["company"] == "ThermalBiz ESCO"
    assert document["stock_items"] == [
        {"item_code": "R404A-GAS-CYLINDER", "warehouse": "Kho Vat Tu - TB", "consumed_quantity": "2"}
    ]


def test_a_live_sends_frappe_datetime_format(state_dir):
    """failure_date la kieu Datetime cua Frappe, va phai la luc su co xay ra."""
    mod = live_connector_a(state_dir)
    stub = HttpStub({("POST", "/api/resource/Asset Repair"): FakeResponse(201, {"data": {}})})
    mod.requests = stub

    start_ts_ms = 1_767_225_600_000  # 2026-01-01T00:00:00Z
    with TestClient(mod.app) as client:
        client.post(
            "/webhook/thingsboard-alarm",
            json={**ALARM, "alarm_id": "ts-1", "start_ts": start_ts_ms},
            headers=auth_headers(),
        )

    assert stub.bodies("/api/resource/Asset Repair")[0]["failure_date"] == "2026-01-01 00:00:00"


def test_a_live_omits_refrigerant_for_unrelated_alarm(state_dir):
    mod = live_connector_a(state_dir)
    stub = HttpStub({("POST", "/api/resource/Asset Repair"): FakeResponse(201, {"data": {}})})
    mod.requests = stub

    with TestClient(mod.app) as client:
        client.post(
            "/webhook/thingsboard-alarm",
            json={**ALARM, "alarm_id": "no-gas-1", "alarm_type": "DOOR_OPEN", "severity": "INFO"},
            headers=auth_headers(),
        )

    document = stub.bodies("/api/resource/Asset Repair")[0]
    assert document["stock_items"] == []
    assert document["stock_consumption"] == 0


def test_a_live_auth_header_is_frappe_token_format(state_dir):
    mod = live_connector_a(state_dir)
    stub = HttpStub({("POST", "/api/resource/Asset Repair"): FakeResponse(201, {"data": {}})})
    mod.requests = stub

    with TestClient(mod.app) as client:
        client.post("/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "auth-1"}, headers=auth_headers())

    headers = stub.calls[0][2]["headers"]
    assert headers["Authorization"] == "token erp-key:erp-secret"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(400, 422), (403, 422), (404, 422), (417, 422), (500, 502), (503, 502)],
)
def test_a_live_maps_erpnext_status_codes(state_dir, status_code, expected):
    """4xx la loi contract - retry vo ich, phai noi ro. 5xx moi la loi mang."""
    mod = live_connector_a(state_dir)
    stub = HttpStub({("POST", "/api/resource/Asset Repair"): FakeResponse(status_code, {"error": "boom"})})
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": f"code-{status_code}"}, headers=auth_headers()
        )

    assert response.status_code == expected


def test_a_live_unwraps_frappe_server_messages(state_dir):
    """Fappe nest loi trong _server_messages (JSON trong JSON). Boc ra de nguoi van hanh doc duoc."""
    mod = live_connector_a(state_dir)
    server_messages = json.dumps([{"message": "Asset is mandatory", "indicator": "red"}])
    stub = HttpStub(
        {("POST", "/api/resource/Asset Repair"): FakeResponse(417, {"_server_messages": server_messages})}
    )
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "msg-1"}, headers=auth_headers()
        )

    assert response.status_code == 422
    assert "Asset is mandatory" in response.json()["detail"]


def test_a_live_network_error_is_502(state_dir):
    mod = live_connector_a(state_dir)
    mod.requests = HttpStub({("POST", "/api/resource/Asset Repair"): network_error})

    with TestClient(mod.app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "net-1"}, headers=auth_headers()
        )

    assert response.status_code == 502


# =========================================================================== #
# Connector A - cooldown
# =========================================================================== #
def test_a_cooldown_suppresses_duplicate_alarm(state_dir):
    with TestClient(connector_a(state_dir).app) as client:
        first = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "dup-alarm-999"}, headers=auth_headers()
        )
        second = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "dup-alarm-999"}, headers=auth_headers()
        )
    assert first.json()["status"] == "simulated"
    assert second.json()["status"] == "cooldown_suppressed"


def test_a_cooldown_survives_restart(state_dir):
    """Cooldown nam trong dict cua ban cu -> restart la mat, spam phieu sua chua."""
    with TestClient(connector_a(state_dir).app) as client:
        client.post("/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "restart-1"}, headers=auth_headers())

    reloaded = connector_a(state_dir)
    assert reloaded._read_cooldowns().get("restart-1") is not None

    with TestClient(reloaded.app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "restart-1"}, headers=auth_headers()
        )
    assert response.json()["status"] == "cooldown_suppressed"


def test_a_alarm_without_id_is_never_suppressed(state_dir):
    with TestClient(connector_a(state_dir).app) as client:
        payload = {key: value for key, value in ALARM.items() if key != "alarm_id"}
        first = client.post("/webhook/thingsboard-alarm", json=payload, headers=auth_headers())
        second = client.post("/webhook/thingsboard-alarm", json=payload, headers=auth_headers())
    assert first.json()["status"] == second.json()["status"] == "simulated"


# =========================================================================== #
# Connector B - bao mat va cau hinh
# =========================================================================== #
def test_b_refuses_to_start_without_api_key(state_dir):
    with pytest.raises(RuntimeError, match="CONNECTOR_API_KEY"):
        connector_b(state_dir, CONNECTOR_API_KEY="")


def test_b_refuses_to_start_without_backend(state_dir):
    """Connector khong con giu don gia, nen thieu backend la khong the tinh duoc tien."""
    with pytest.raises(RuntimeError, match="BACKEND_URL"):
        live_connector_b(state_dir, BACKEND_URL="")


def test_b_refuses_to_start_without_tenant_map(state_dir):
    with pytest.raises(RuntimeError, match="TENANT_CLIENT_MAP"):
        live_connector_b(state_dir, TENANT_CLIENT_MAP="{}")


def test_b_rejects_missing_api_key(state_dir):
    with TestClient(connector_b(state_dir).app) as client:
        assert client.post("/api/generate-invoice", json=METER_BODY).status_code == 401


def test_b_ignores_caller_supplied_client_id(state_dir):
    with TestClient(connector_b(state_dir).app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "client_id": "attacker-chosen-client", "simulated_reading_kwh": 100.0},
            headers=auth_headers(),
        )
    assert response.status_code == 200
    assert "attacker-chosen-client" not in response.text
    assert response.json()["client_id"] == "ninja-client-77"


def test_b_rejects_unmapped_tenant(state_dir):
    with TestClient(connector_b(state_dir).app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "tenant_code": "KHONG_TON_TAI", "simulated_reading_kwh": 100.0},
            headers=auth_headers(),
        )
    assert response.status_code == 404


@pytest.mark.parametrize("entity_id", ["../etc/passwd", "KHONG HOP LE", "a.b.c", ""])
def test_b_rejects_malformed_entity_id(state_dir, entity_id):
    with TestClient(connector_b(state_dir).app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "sensor_entity_id": entity_id, "simulated_reading_kwh": 100.0},
            headers=auth_headers(),
        )
    assert response.status_code == 422


def test_b_rejects_simulated_reading_on_the_live_path(state_dir):
    """Duong chay that ma nhan chi so tu nguoi goi thi ho tu khai duoc san luong dien."""
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes())
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "simulated_reading_kwh": 999_999.0},
            headers=auth_headers(),
        )

    assert response.status_code == 422
    assert stub.calls == []


# =========================================================================== #
# Connector B - che do mo phong khong duoc bia ra tien
# =========================================================================== #
def test_b_simulation_does_not_invent_money(state_dir):
    with TestClient(connector_b(state_dir).app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "billing_period": "2026-09", "simulated_reading_kwh": 10_500.0},
            headers=auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "simulated"
    assert body["pricing"] == "not_calculated"
    assert "total_vnd" not in body
    assert "tou_distribution" not in body


def test_b_simulation_requires_a_reading(state_dir):
    with TestClient(connector_b(state_dir).app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )
    assert response.status_code == 422


def test_b_simulation_shows_exactly_what_would_be_sent(state_dir):
    with TestClient(connector_b(state_dir).app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "billing_period": "2026-09", "simulated_reading_kwh": 10_500.0},
            headers=auth_headers(),
        )

    request = response.json()["backend_request"]
    assert request == {
        "tenant_code": "KHO_DONG_01",
        "entity_id": ENTITY_ID,
        "period_start": "2026-09-01T00:00:00",
        "period_end": "2026-10-01T00:00:00",
        "current_reading_kwh": 10_500.0,
        "source": "SIMULATION",
    }
    # Backend tu lay chi so ky truoc. Gui previous_reading_kwh len la tuyen bo sai su that.
    assert "previous_reading_kwh" not in request


def test_b_invoice_number_is_deterministic(state_dir):
    mod = connector_b(state_dir)
    first = mod.invoice_number("KHO_DONG_01", mod._month_bounds(2026, 9)[0])
    second = mod.invoice_number("KHO_DONG_01", mod._month_bounds(2026, 9)[0])
    assert first == second == "ESC-KHO-DONG-01-202609"


@pytest.mark.parametrize(
    ("period_start", "expected_start", "expected_end"),
    [
        ("2026-09-01T00:00:00Z", "2026-09-01T00:00:00", "2026-10-01T00:00:00"),
        ("2026-09-01T07:00:00+07:00", "2026-09-01T00:00:00", "2026-10-01T00:00:00"),
    ],
)
def test_b_normalizes_explicit_period_to_naive_utc(state_dir, period_start, expected_start, expected_end):
    """Backend luu datetime naive-UTC; gui aware sang thi SQLite so sanh se TypeError."""
    with TestClient(connector_b(state_dir).app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={
                **METER_BODY,
                "period_start": period_start,
                "period_end": "2026-10-01T00:00:00Z",
                "simulated_reading_kwh": 10_500.0,
            },
            headers=auth_headers(),
        )

    request = response.json()["backend_request"]
    assert request["period_start"] == expected_start
    assert request["period_end"] == expected_end


def test_b_rejects_half_an_explicit_period(state_dir):
    with TestClient(connector_b(state_dir).app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "period_start": "2026-09-01T00:00:00Z", "simulated_reading_kwh": 1.0},
            headers=auth_headers(),
        )
    assert response.status_code == 422


# =========================================================================== #
# Connector B - duong that (truoc day KHONG duoc test)
# =========================================================================== #
def test_b_never_invents_a_reading_when_ha_is_down(state_dir):
    mod = live_connector_b(state_dir)
    mod.requests = HttpStub({("GET", HA_STATE_URL): network_error})

    with TestClient(mod.app) as client:
        response = client.post("/api/generate-invoice", json=METER_BODY, headers=auth_headers())

    assert response.status_code == 503
    assert "1250" not in response.text
    assert response.json().get("status") != "success"


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
def test_b_rejects_unavailable_sensor_state(state_dir, state):
    mod = live_connector_b(state_dir)
    mod.requests = HttpStub({("GET", HA_STATE_URL): FakeResponse(200, {"state": state})})

    with TestClient(mod.app) as client:
        response = client.post("/api/generate-invoice", json=METER_BODY, headers=auth_headers())

    assert response.status_code == 503


def test_b_rejects_negative_cumulative_reading(state_dir):
    mod = live_connector_b(state_dir)
    mod.requests = HttpStub({("GET", HA_STATE_URL): FakeResponse(200, {"state": "-5"})})

    with TestClient(mod.app) as client:
        response = client.post("/api/generate-invoice", json=METER_BODY, headers=auth_headers())

    assert response.status_code == 503


def test_b_live_bills_electricity_not_just_the_service_fee(state_dir):
    """Hoi sinh loi that thu: ban cu tinh total = kWh x phi dich vu, tien dien = 0."""
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes())
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["electricity_vnd"] == ELECTRICITY_VND
    assert body["service_fee_vnd"] == SERVICE_VND
    assert body["total_vnd"] == ELECTRICITY_VND + SERVICE_VND
    assert ELECTRICITY_VND > 0

    sent = stub.bodies(NINJA_INVOICE_URL)[0]
    # Tong gia tri cac dong phai bang dung tong tien backend tinh. Khong duoc rot tien dien.
    assert sum(round(item["cost"] * item["quantity"]) for item in sent["line_items"]) == body["total_vnd"]


def test_b_live_line_items_come_from_backend_prices(state_dir):
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes())
    mod.requests = stub

    with TestClient(mod.app) as client:
        client.post("/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers())

    items = {item["product_key"]: item for item in stub.bodies(NINJA_INVOICE_URL)[0]["line_items"]}
    assert set(items) == {"EVN_PEAK_ENERGY", "EVN_NORMAL_ENERGY", "EVN_OFF_PEAK_ENERGY", "COLD_STORAGE_SERVICE"}

    for band, product_key in [("PEAK", "EVN_PEAK_ENERGY"), ("NORMAL", "EVN_NORMAL_ENERGY"), ("OFF_PEAK", "EVN_OFF_PEAK_ENERGY")]:
        assert items[product_key]["cost"] == PRICES[band]
        assert items[product_key]["quantity"] == BANDS[band]

    assert items["COLD_STORAGE_SERVICE"]["cost"] == SERVICE_RATE
    assert items["COLD_STORAGE_SERVICE"]["quantity"] == TOTAL_KWH


def test_b_live_ignores_caller_supplied_prices(state_dir):
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes())
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={
                **METER_BODY,
                "billing_period": "2026-09",
                "service_rate_per_kwh": 1,
                "evn_peak_rate_vnd": 1,
                "total_vnd": 1,
            },
            headers=auth_headers(),
        )

    assert response.status_code == 200
    backend_body = stub.bodies(BACKEND_BILLING_URL)[0]
    assert set(backend_body) == {
        "tenant_code", "entity_id", "period_start", "period_end", "current_reading_kwh", "source"
    }
    assert response.json()["total_vnd"] == ELECTRICITY_VND + SERVICE_VND


def test_b_live_sends_cumulative_reading_and_no_baseline(state_dir):
    """Backend tu suy ra delta va tu bao loi neu chua co goc. Connector khong duoc doan."""
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes(cumulative=10_500.0))
    mod.requests = stub

    with TestClient(mod.app) as client:
        client.post("/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers())

    method, url, kwargs = stub.calls[1]
    assert (method, url) == ("POST", "http://backend.test/api/ingest/billing")
    assert kwargs["headers"]["X-Connector-Api-Key"] == BACKEND_KEY
    assert kwargs["json"]["current_reading_kwh"] == 10_500.0
    assert kwargs["json"]["source"] == "HA"
    assert "previous_reading_kwh" not in kwargs["json"]


@pytest.mark.parametrize("backend_status", [404, 409, 422, 503])
def test_b_live_passes_backend_rejections_through(state_dir, backend_status):
    """Cong to quay so (409), thieu ky goc (422)... phai den tay nguoi van hanh nguyen ven."""
    mod = live_connector_b(state_dir)
    routes = live_b_routes()
    routes[("POST", BACKEND_BILLING_URL)] = FakeResponse(backend_status, {"detail": "Chi so cong to tut"})
    stub = HttpStub(routes)
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    expected = backend_status if backend_status < 500 else 502
    assert response.status_code == expected
    assert "Chi so cong to tut" in response.json()["detail"]
    # Quan trong nhat: KHONG duoc tao hoa don khi backend da tu choi.
    assert stub.count(NINJA_INVOICE_URL) == 0


def test_b_live_does_not_reissue_when_backend_already_linked(state_dir):
    """Khoa idempotency that: cot unique external_invoice_id o backend, khong phai file JSON."""
    mod = live_connector_b(state_dir)
    invoice = backend_invoice(external_invoice_id="INV-OLD", duplicated_call=True)
    stub = HttpStub(live_b_routes(invoice=invoice))
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    body = response.json()
    assert body["status"] == "already_billed"
    assert body["external_invoice_id"] == "INV-OLD"
    assert stub.count(NINJA_INVOICE_URL) == 0


def test_b_live_skips_zero_value_invoice(state_dir):
    mod = live_connector_b(state_dir)
    invoice = backend_invoice(total_kwh=0.0, electricity_vnd=0, service_fee_vnd=0, total_vnd=0)
    stub = HttpStub(live_b_routes(invoice=invoice))
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    assert response.json()["status"] == "no_charge"
    assert stub.count(NINJA_INVOICE_URL) == 0


def test_b_live_survives_a_request_without_billing_period(state_dir):
    """Hoi sinh NameError: ban cu chi bind idempotency_key khi co billing_period,
    nhung lai dung no sau khi Invoice Ninja DA tao hoa don -> 500, va retry thanh hoa don doi.
    """
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes())
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post("/api/generate-invoice", json=METER_BODY, headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert stub.count(NINJA_INVOICE_URL) == 1


def test_b_live_records_external_reference_back_to_backend(state_dir):
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes())
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    body = response.json()
    assert body["external_reference_recorded"] is True
    assert body["external_invoice_id"] == "INV-9"

    method, url, kwargs = stub.calls[-1]
    assert method == "PATCH"
    assert url == "http://backend.test/api/ingest/billing/41/external-reference"
    assert kwargs["json"] == {"external_invoice_id": "INV-9"}


def test_b_live_dead_letters_when_reference_write_back_fails(state_dir):
    """Hoa don that da ton tai -> van tra ve success, nhung phai de lai dau vet doi soat."""
    mod = live_connector_b(state_dir)
    routes = live_b_routes()
    routes[("PATCH", EXTERNAL_REF_URL)] = FakeResponse(500, {"detail": "db down"})
    stub = HttpStub(routes)
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["external_reference_recorded"] is False

    entries = dead_letters(mod)
    assert len(entries) == 1
    assert entries[0]["stage"] == "backend_external_reference"
    assert entries[0]["external_invoice_id"] == "INV-9"


def test_b_live_dead_letters_when_ninja_returns_no_id(state_dir):
    """Khong co id thi khong the gan khoa idempotency. Doan mo hoac bao loi, khong im lang."""
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes(ninja_response={"message": "created"}))
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    assert response.status_code == 502
    assert dead_letters(mod)[0]["stage"] == "invoice_ninja_id_missing"


def test_b_live_retries_then_dead_letters_on_ninja_5xx(state_dir):
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes(ninja_response=FakeResponse(500, {"detail": "ninja down"})))
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    assert response.status_code == 502
    assert stub.count(NINJA_INVOICE_URL) == mod.MAX_RETRIES
    assert dead_letters(mod)[0]["stage"] == "invoice_ninja"


def test_b_live_does_not_retry_ninja_4xx(state_dir):
    """4xx la payload sai. Goi lai 3 lan chi lam cham viec bao loi."""
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes(ninja_response=FakeResponse(400, {"message": "client_id invalid"})))
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    assert response.status_code == 502
    assert stub.count(NINJA_INVOICE_URL) == 1
    assert "client_id invalid" in response.json()["detail"]
    assert dead_letters(mod) == []


def test_b_live_labels_the_estimate_on_the_invoice(state_dir):
    """Khi backend uoc luong theo gio, hoa don phai noi ro - khong duoc gia vo la so do."""
    mod = live_connector_b(state_dir)
    invoice = backend_invoice()
    invoice["breakdown"]["split_method"] = "hours_estimate"
    invoice["breakdown"]["warnings"] = ["Delta kWh = 0: thiet bi khong van hanh trong ky"]
    stub = HttpStub(live_b_routes(invoice=invoice))
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    assert response.json()["split_method"] == "hours_estimate"
    notes = stub.bodies(NINJA_INVOICE_URL)[0]["public_notes"]
    assert "UOC LUONG" in notes
    assert "Delta kWh = 0" in notes


def test_b_live_states_measured_split_when_telemetry_exists(state_dir):
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes())
    mod.requests = stub

    with TestClient(mod.app) as client:
        client.post("/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers())

    notes = stub.bodies(NINJA_INVOICE_URL)[0]["public_notes"]
    assert "UOC LUONG" not in notes
    assert "du lieu cong to do duoc" in notes


def test_b_live_sends_deterministic_invoice_number(state_dir):
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes())
    mod.requests = stub

    with TestClient(mod.app) as client:
        response = client.post(
            "/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers()
        )

    assert stub.bodies(NINJA_INVOICE_URL)[0]["number"] == "ESC-KHO-DONG-01-202609"
    assert response.json()["invoice_number"] == "ESC-KHO-DONG-01-202609"


def test_b_live_auth_headers_are_correct_per_service(state_dir):
    mod = live_connector_b(state_dir)
    stub = HttpStub(live_b_routes())
    mod.requests = stub

    with TestClient(mod.app) as client:
        client.post("/api/generate-invoice", json={**METER_BODY, "billing_period": "2026-09"}, headers=auth_headers())

    by_url = {url: kwargs for _, url, kwargs in stub.calls}
    ha_call = next(kwargs for url, kwargs in by_url.items() if url.endswith(HA_STATE_URL))
    ninja_call = next(kwargs for url, kwargs in by_url.items() if url.endswith(NINJA_INVOICE_URL))

    assert ha_call["headers"] == {"Authorization": "Bearer ha-token"}
    assert ninja_call["headers"]["X-Api-Token"] == "ninja-token"
    # Khoa connector khong duoc ri sang he thong khac.
    assert "X-Connector-Api-Key" not in ninja_call["headers"]
    assert "X-Api-Token" not in ha_call["headers"]


def test_b_health_reports_backend_as_pricing_owner(state_dir):
    with TestClient(live_connector_b(state_dir).app) as client:
        body = client.get("/health").json()
    assert body["pricing_owner"] == "backend"
    assert body["simulation_mode"] is False
