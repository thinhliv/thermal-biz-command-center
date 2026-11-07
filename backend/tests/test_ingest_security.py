"""Bao mat tang ingest: connector API key, va cac truong client KHONG duoc tu khai.

Repo nay PUBLIC. Nhung gi duoc kiem tra o day la nhung thu da tung hong:
- endpoint /api/ingest/* mo toang, ai goi cung duoc;
- nguoi goi tu khai `client_id` -> xuat hoa don cho khach hang bat ky;
- nguoi goi tu khai `service_rate_per_kwh` -> tu dinh gia phi quan ly;
- nguoi goi tu khai `cop` -> che giau thiet bi dang kem hieu nang.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.main import app
from app.models import BilledInvoice, Equipment, EquipmentKind, MeterReading, TelemetrySample
from app.schemas import BillingRequest, TelemetryIn
from app.security import get_current_user, require_connector_key
from app.timeutil import month_bounds, utcnow

KEY_VALUE = "test-connector-api-key"
KEY = {"X-Connector-Api-Key": KEY_VALUE}

#: Nhung endpoint /api CO Y de mo (khong JWT, khong connector key).
PUBLIC_ENDPOINTS = {
    ("GET", "/api/health"),
    ("GET", "/api/system/config"),
    ("GET", "/api/ingest/health"),
    ("POST", "/api/auth/login"),
}


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def ingest(session: Session) -> Session:
    """DB co 1 kho lanh (co tenant + cong to) va 1 lo hoi, khong co du lieu billing."""
    from app.seed import seed_tariff_bands

    seed_tariff_bands(session)
    session.add_all(
        [
            Equipment(
                code="KHO_THUE_01",
                name="Kho dong cho thue An Phat",
                kind=EquipmentKind.DEEP_FREEZER.value,
                rated_power_kw=38.0,
                design_cop=3.6,
                haccp_limit_c=-18.0,
                tenant_code="THUE-ANPHAT",
                meter_entity_id="sensor.anphat_kho_dong_energy",
                is_active=True,
            ),
            Equipment(
                code="LO_HOI_01",
                name="Lo hoi sinh khoi so 1",
                kind=EquipmentKind.BOILER.value,
                rated_power_kw=48.0,
                design_efficiency_pct=85.0,
                is_active=True,
            ),
        ]
    )
    session.commit()
    return session


@pytest.fixture()
def api(ingest: Session) -> TestClient:
    return TestClient(app)


def _period() -> tuple[datetime, datetime]:
    return month_bounds(utcnow() - timedelta(days=45))


def _billing_payload(**kw) -> dict:
    start, end = _period()
    body = {
        "tenant_code": "THUE-ANPHAT",
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "previous_reading_kwh": 10_000.0,
        "current_reading_kwh": 10_500.0,
        "source": "MANUAL",
    }
    body.update(kw)
    return body


# --------------------------------------------------------------------------- #
# Audit toan bo mat cat API: khong duoc them endpoint "quen" gan auth
# --------------------------------------------------------------------------- #
def _walk(routes):
    """Starlette 1.x boc router da include trong _IncludedRouter -> phai de quy."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _walk(inner.routes)
        else:
            yield route


def _requires(dependant, guard) -> bool:
    if dependant is None:
        return False
    if dependant.call is guard:
        return True
    return any(_requires(child, guard) for child in dependant.dependencies)


def test_moi_endpoint_api_deu_co_auth_tru_danh_sach_cho_phep():
    unguarded = []
    for route in _walk(app.routes):
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        dependant = getattr(route, "dependant", None)
        secured = _requires(dependant, get_current_user) or _requires(dependant, require_connector_key)
        for method in sorted(getattr(route, "methods", []) or ["WS"]):
            if not secured and (method, path) not in PUBLIC_ENDPOINTS:
                unguarded.append(f"{method} {path}")

    assert unguarded == [], f"Endpoint khong co xac thuc: {unguarded}"


def test_bon_endpoint_ingest_deu_khoa_bang_connector_key():
    guarded = {
        (method, route.path)
        for route in _walk(app.routes)
        for method in (getattr(route, "methods", None) or [])
        if route.path.startswith("/api/ingest") and _requires(getattr(route, "dependant", None), require_connector_key)
    }
    assert guarded == {
        ("GET", "/api/ingest/tenants"),
        ("POST", "/api/ingest/telemetry"),
        ("POST", "/api/ingest/telemetry/batch"),
        ("POST", "/api/ingest/billing"),
    }


# --------------------------------------------------------------------------- #
# Connector API key
# --------------------------------------------------------------------------- #
def test_ingest_health_la_public(api: TestClient):
    response = api.get("/api/ingest/health")
    assert response.status_code == 200
    assert response.json()["equipment_registered"] == 2


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/ingest/tenants", None),
        ("POST", "/api/ingest/telemetry", {"equipment_code": "KHO_THUE_01", "temperature_c": -25.0}),
        ("POST", "/api/ingest/telemetry/batch", {"samples": [{"equipment_code": "KHO_THUE_01", "temperature_c": -25.0}]}),
        ("POST", "/api/ingest/billing", None),
    ],
)
def test_tu_choi_khi_thieu_hoac_sai_connector_key(api: TestClient, method: str, path: str, body):
    body = body if body is not None else _billing_payload()

    missing = api.request(method, path, json=body)
    wrong = api.request(method, path, json=body, headers={"X-Connector-Api-Key": "sai-be-ke-tu"})
    # Doan dung 1 ky tu cuoi cung van phai truot: khoa bang compare_digest, khong startswith
    prefix = api.request(method, path, json=body, headers={"X-Connector-Api-Key": KEY_VALUE[:-1]})

    assert (missing.status_code, wrong.status_code, prefix.status_code) == (401, 401, 401)


def test_chap_nhan_key_dung(api: TestClient):
    assert api.get("/api/ingest/tenants", headers=KEY).status_code == 200


def test_jwt_khong_dung_duoc_lam_connector_key(api: TestClient):
    """Hai co che khac nhau: token nguoi dung khong mo duoc cua may-goi-may."""
    response = api.get("/api/ingest/tenants", headers={"X-Connector-Api-Key": "Bearer anything.at.all"})
    assert response.status_code == 401


def test_chua_cau_hinh_key_thi_dong_cua_chu_khong_mo(api: TestClient, monkeypatch):
    """Fail CLOSED. Thieu CONNECTOR_API_KEY -> 503, khong phai 'ai vao cung duoc'."""
    monkeypatch.setattr(get_settings(), "connector_api_key", "")

    assert api.get("/api/ingest/tenants", headers=KEY).status_code == 503
    assert api.get("/api/ingest/tenants").status_code == 503


def test_tenants_chi_liet_ke_thiet_bi_dang_ky_cho_thue(api: TestClient):
    tenants = api.get("/api/ingest/tenants", headers=KEY).json()["tenants"]
    assert [t["tenant_code"] for t in tenants] == ["THUE-ANPHAT"]
    assert tenants[0]["meter_entity_id"] == "sensor.anphat_kho_dong_energy"


# --------------------------------------------------------------------------- #
# Client khong duoc tu khai nhung truong trong yeu
# --------------------------------------------------------------------------- #
def test_billing_request_khong_co_truong_client_id():
    """Neu co, nguoi goi se xuat duoc hoa don cho khach hang bat ky."""
    assert "client_id" not in BillingRequest.model_fields
    assert "customer_id" not in BillingRequest.model_fields


def test_billing_request_khong_co_truong_don_gia():
    assert "service_rate_per_kwh" not in BillingRequest.model_fields
    assert "price_vnd_per_kwh" not in BillingRequest.model_fields
    assert "total_vnd" not in BillingRequest.model_fields


def test_telemetry_request_khong_co_truong_cop():
    """COP la ket qua tinh tu Q_o / N_e o backend, khong phai dau vao."""
    assert "cop" not in TelemetryIn.model_fields


def test_gui_len_service_rate_rieng_van_bi_bo_qua(api: TestClient, ingest: Session):
    response = api.post("/api/ingest/billing", headers=KEY, json=_billing_payload(service_rate_per_kwh=1))
    assert response.status_code == 200, response.text

    body = response.json()
    rate = get_settings().service_rate_per_kwh
    # 500 kWh x don gia cua SERVER, khong phai 1 dong nhu nguoi goi khai
    assert body["total_kwh"] == 500.0
    assert body["service_fee_vnd"] == int(500 * rate)
    assert body["service_fee_vnd"] > 0


def test_gui_len_client_id_rieng_van_bi_bo_qua(api: TestClient, ingest: Session):
    response = api.post(
        "/api/ingest/billing",
        headers=KEY,
        json=_billing_payload(client_id=999, customer_id=999, tenant_code="THUE-ANPHAT"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["tenant_code"] == "THUE-ANPHAT"

    stored = ingest.scalars(select(BilledInvoice)).one()
    assert stored.tenant_code == "THUE-ANPHAT"


def test_gui_len_cop_khung_van_bi_tinh_lai_tu_qo_va_ne(api: TestClient, ingest: Session):
    api.post(
        "/api/ingest/telemetry",
        headers=KEY,
        json={
            "equipment_code": "KHO_THUE_01",
            "power_kw": 40.0,
            "cooling_capacity_kw": 120.0,
            "cop": 99.0,
        },
    )

    sample = ingest.scalars(select(TelemetrySample)).one()
    assert sample.cop == 3.0  # 120 / 40, khong phai 99


def test_thieu_cong_suat_lanh_thi_cop_la_null_khong_phai_so_khong(api: TestClient, ingest: Session):
    api.post("/api/ingest/telemetry", headers=KEY, json={"equipment_code": "KHO_THUE_01", "power_kw": 40.0})
    assert ingest.scalars(select(TelemetrySample)).one().cop is None


def test_lo_hoi_khong_duoc_ghi_cop_va_kho_lanh_khong_duoc_ghi_eta(api: TestClient, ingest: Session):
    api.post(
        "/api/ingest/telemetry/batch",
        headers=KEY,
        json={
            "samples": [
                {"equipment_code": "LO_HOI_01", "power_kw": 48.0, "cooling_capacity_kw": 200.0, "efficiency_pct": 81.0},
                {"equipment_code": "KHO_THUE_01", "power_kw": 40.0, "cooling_capacity_kw": 140.0, "efficiency_pct": 81.0},
            ]
        },
    )

    by_code = {s.equipment.code: s for s in ingest.scalars(select(TelemetrySample))}
    assert by_code["LO_HOI_01"].cop is None
    assert by_code["LO_HOI_01"].efficiency_pct == 81.0
    assert by_code["KHO_THUE_01"].efficiency_pct is None
    assert by_code["KHO_THUE_01"].cop == 3.5


# --------------------------------------------------------------------------- #
# Kiem tra dau vao telemetry
# --------------------------------------------------------------------------- #
def test_thiet_bi_chua_dang_ky_bi_tu_choi(api: TestClient, ingest: Session):
    response = api.post(
        "/api/ingest/telemetry", headers=KEY, json={"equipment_code": "KHO_LA", "temperature_c": -20.0}
    )
    assert response.status_code == 404
    assert ingest.scalars(select(TelemetrySample)).first() is None


def test_batch_tach_ro_mau_hop_le_va_khong_hop_le(api: TestClient, ingest: Session):
    response = api.post(
        "/api/ingest/telemetry/batch",
        headers=KEY,
        json={
            "samples": [
                {"equipment_code": "KHO_THUE_01", "temperature_c": -25.0},
                {"equipment_code": "KHO_KHONG_TON_TAI", "temperature_c": -25.0},
                {"equipment_code": "LO_HOI_01", "temperature_c": 90.0},
            ]
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["accepted"] == 2
    assert [r["index"] for r in body["rejected"]] == [1]
    assert len(list(ingest.scalars(select(TelemetrySample)))) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"equipment_code": "KHO_THUE_01"},  # rong: khong chi so, khong trang thai
        {"equipment_code": "KHO_THUE_01", "temperature_c": 9000},  # lo hoi cung khong nong the
        {"equipment_code": "KHO_THUE_01", "temperature_c": -200},
        {"equipment_code": "KHO_THUE_01", "power_kw": -5},
        {"equipment_code": "KHO_THUE_01", "efficiency_pct": 150},
        {"equipment_code": "KHO_THUE_01", "vibration_mm_s": -1},
        {"equipment_code": "KHO_THUE_01", "energy_kwh_cumulative": -100},
        {"equipment_code": "", "temperature_c": -25.0},
    ],
)
def test_mau_telemetry_vo_ly_bi_chan_422(api: TestClient, payload):
    assert api.post("/api/ingest/telemetry", headers=KEY, json=payload).status_code == 422


# --------------------------------------------------------------------------- #
# Kiem tra dau vao billing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_code": ""},
        {"current_reading_kwh": -1},
        {"previous_reading_kwh": -1},
        {"entity_id": "KHONG HOP LE"},
        {"entity_id": "a.b.c"},
        {"source": "TU_KHAI"},
    ],
)
def test_billing_request_vo_ly_bi_chan_422(api: TestClient, overrides):
    assert api.post("/api/ingest/billing", headers=KEY, json=_billing_payload(**overrides)).status_code == 422


def test_ky_billing_nguoc_thoi_gian_bi_chan(api: TestClient):
    start, end = _period()
    response = api.post(
        "/api/ingest/billing",
        headers=KEY,
        json=_billing_payload(period_start=end.isoformat(), period_end=start.isoformat()),
    )
    assert response.status_code == 422


def test_ky_billing_qua_400_ngay_bi_chan(api: TestClient):
    start, _ = _period()
    response = api.post(
        "/api/ingest/billing",
        headers=KEY,
        json=_billing_payload(period_start=start.isoformat(), period_end=(start + timedelta(days=401)).isoformat()),
    )
    assert response.status_code == 422


def test_chi_so_cong_to_tut_doi_tra_ve_409_va_khong_luu_hoa_don(api: TestClient, ingest: Session):
    """Cong to thay moi / quay so. Bao 409 de nguoi van hanh vao xu ly, khong tu 'boc' ra so."""
    start, end = _period()
    ingest.add(
        MeterReading(
            tenant_code="THUE-ANPHAT",
            period_start=start - timedelta(days=31),
            period_end=start,
            reading_start_kwh=9_000.0,
            reading_end_kwh=10_000.0,
            delta_kwh=1_000.0,
            source="MANUAL",
        )
    )
    ingest.commit()

    response = api.post("/api/ingest/billing", headers=KEY, json=_billing_payload(current_reading_kwh=9_500.0))

    assert response.status_code == 409
    assert ingest.scalars(select(BilledInvoice)).first() is None


def test_delta_kwh_bat_thuong_so_voi_cong_suat_dat_bi_chan(api: TestClient, ingest: Session):
    """38 kW x 720h x 1.5 = 41,040 kWh la tran hop ly. Khai 900,000 kWh -> tu choi."""
    response = api.post("/api/ingest/billing", headers=KEY, json=_billing_payload(current_reading_kwh=910_000.0))
    assert response.status_code == 422
    assert ingest.scalars(select(BilledInvoice)).first() is None


def test_thieu_chi_so_ky_truoc_thi_bao_loi_khong_doa(api: TestClient, ingest: Session):
    response = api.post("/api/ingest/billing", headers=KEY, json=_billing_payload(previous_reading_kwh=None))
    assert response.status_code == 422
    assert ingest.scalars(select(BilledInvoice)).first() is None


def test_goi_lai_dung_ky_tra_ve_hoa_don_cu(api: TestClient, ingest: Session):
    """Connector retry sau timeout khong duoc xuat hoa don doi."""
    payload = _billing_payload()
    first = api.post("/api/ingest/billing", headers=KEY, json=payload).json()
    second = api.post("/api/ingest/billing", headers=KEY, json=payload).json()

    assert second["duplicated_call"] is True
    assert second["id"] == first["id"]
    assert second["total_vnd"] == first["total_vnd"]
    assert len(list(ingest.scalars(select(BilledInvoice)))) == 1
