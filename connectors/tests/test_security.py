"""
Kiem chung cac lop bao mat cua 2 connector:
  - Endpoint khong con mo (bat buoc X-Connector-API-Key)
  - client_id cua Invoice Ninja khong con do nguoi goi tu khai
  - Don gia dich vu den tu server, khong tu request
  - Khong bao gio xuat hoa don dua tren so lieu gia lap khi HA loi
"""

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

CONNECTORS_DIR = Path(__file__).resolve().parents[1]
CONNECTOR_A_PATH = CONNECTORS_DIR / "thingsboard-to-erpnext" / "app.py"
CONNECTOR_B_PATH = CONNECTORS_DIR / "ha-to-invoiceninja" / "app.py"

API_KEY = "test-connector-key"
TENANT_MAP = {"KHO_DONG_01": "ninja-client-77"}

MANAGED_ENV_KEYS = (
    "ERPNEXT_URL", "ERPNEXT_API_KEY", "ERPNEXT_API_SECRET",
    "HASS_URL", "HASS_TOKEN", "INVOICE_NINJA_URL", "INVOICE_NINJA_TOKEN",
    "CONNECTOR_API_KEY", "SIMULATION_MODE", "TENANT_CLIENT_MAP",
    "SERVICE_RATE_PER_KWH",
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


def load_connector(path: Path, module_name: str, env: dict) -> ModuleType:
    """Import app.py voi mot bo bien moi truong rieng (config doc luc import)."""
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


def connector_a(**overrides) -> ModuleType:
    return load_connector(
        CONNECTOR_A_PATH,
        "connector_a_under_test",
        {"CONNECTOR_API_KEY": API_KEY, "SIMULATION_MODE": "true", **overrides},
    )


def connector_b(**overrides) -> ModuleType:
    return load_connector(
        CONNECTOR_B_PATH,
        "connector_b_under_test",
        {
            "CONNECTOR_API_KEY": API_KEY,
            "SIMULATION_MODE": "true",
            "TENANT_CLIENT_MAP": json.dumps(TENANT_MAP),
            "SERVICE_RATE_PER_KWH": "3500",
            **overrides,
        },
    )


def auth_headers() -> dict:
    return {"X-Connector-API-Key": API_KEY}


# ---------------------------------------------------------------- Connector A


def test_a_refuses_to_start_without_api_key():
    with pytest.raises(RuntimeError, match="CONNECTOR_API_KEY"):
        connector_a(CONNECTOR_API_KEY="")


def test_a_rejects_missing_api_key():
    with TestClient(connector_a().app) as client:
        assert client.post("/webhook/thingsboard-alarm", json=ALARM).status_code == 401


def test_a_rejects_wrong_api_key():
    with TestClient(connector_a().app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm",
            json=ALARM,
            headers={"X-Connector-API-Key": "wrong-key"},
        )
    assert response.status_code == 401


def test_a_accepts_valid_api_key():
    with TestClient(connector_a().app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json=ALARM, headers=auth_headers()
        )
    assert response.status_code == 200
    assert response.json()["status"] == "simulated"


def test_a_creates_maintenance_request_and_r404a_hold():
    with TestClient(connector_a().app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "unique-alarm-123"}, headers=auth_headers()
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "simulated"
    maint = data["maintenance_request"]
    assert maint["doctype"] == "Maintenance Request"
    assert maint["asset"] == "KHO_DONG_01"
    stock = data["stock_reservation"]
    assert stock is not None
    assert stock["item_code"] == "R404A-GAS-CYLINDER"
    assert stock["reserved_qty"] == 2.0


def test_a_cooldown_suppresses_duplicate_alarm():
    mod = connector_a()
    with TestClient(mod.app) as client:
        res1 = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "dup-alarm-999"}, headers=auth_headers()
        )
        assert res1.json()["status"] == "simulated"
        res2 = client.post(
            "/webhook/thingsboard-alarm", json={**ALARM, "alarm_id": "dup-alarm-999"}, headers=auth_headers()
        )
        assert res2.json()["status"] == "cooldown_suppressed"


def test_a_rejects_unknown_severity():
    with TestClient(connector_a().app) as client:
        response = client.post(
            "/webhook/thingsboard-alarm",
            json={**ALARM, "severity": "APOCALYPTIC"},
            headers=auth_headers(),
        )
    assert response.status_code == 422


def test_a_health_is_public():
    with TestClient(connector_a().app) as client:
        assert client.get("/health").status_code == 200


# ---------------------------------------------------------------- Connector B


def test_b_refuses_to_start_without_api_key():
    with pytest.raises(RuntimeError, match="CONNECTOR_API_KEY"):
        connector_b(CONNECTOR_API_KEY="")


def test_b_rejects_missing_api_key():
    with TestClient(connector_b().app) as client:
        assert client.post("/api/generate-invoice", json=METER_BODY).status_code == 401


def test_b_ignores_caller_supplied_client_id():
    with TestClient(connector_b().app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "client_id": "attacker-chosen-client"},
            headers=auth_headers(),
        )
    assert response.status_code == 200
    assert "attacker-chosen-client" not in response.text


def test_b_rejects_unmapped_tenant():
    with TestClient(connector_b().app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "tenant_code": "KHONG_TON_TAI"},
            headers=auth_headers(),
        )
    assert response.status_code == 404


def test_b_never_invents_a_reading_when_ha_is_down():
    with TestClient(
        connector_b(
            SIMULATION_MODE="false",
            HASS_URL="http://127.0.0.1:9",
            HASS_TOKEN="some-token",
            INVOICE_NINJA_URL="http://127.0.0.1:9",
            INVOICE_NINJA_TOKEN="some-token",
        ).app
    ) as client:
        response = client.post("/api/generate-invoice", json=METER_BODY, headers=auth_headers())

    assert response.status_code == 503
    assert "1250" not in response.text
    assert response.json().get("status") != "success"


def test_b_rejects_malformed_entity_id():
    with TestClient(connector_b().app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "sensor_entity_id": "../etc/passwd"},
            headers=auth_headers(),
        )
    assert response.status_code == 422


def test_b_uses_server_side_rate_not_caller_rate():
    with TestClient(connector_b(SERVICE_RATE_PER_KWH="4000").app) as client:
        response = client.post(
            "/api/generate-invoice",
            json={**METER_BODY, "service_rate_per_kwh": 1},
            headers=auth_headers(),
        )
    body = response.json()
    assert body["line_item"]["cost"] == 4000
    assert body["total_vnd"] == body["kwh_metered"] * 4000
