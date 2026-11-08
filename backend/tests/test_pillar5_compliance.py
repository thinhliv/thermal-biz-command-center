"""Bo kiem thu Pillar 5: HACCP Food Safety Audit & ESG Carbon Footprint Reporting.

Kiem chung:
  1. Kiem toan tuan thu chuoi lanh thuy hai san theo tieu chuan HACCP (<= -18 C).
  2. Phat hien cac vi pham diem kiem soat toi han (CCP Breaches) va tinh ti le tuan thu.
  3. Phat hanh chung chi kiem toan dien tu kem chu ky so SHA-256.
  4. Tinh toan dau chan carbon ESG Scope 1 (ro ri R404A voi GWP = 3922) va Scope 2 (EVN 0.7221 tCO2/MWh).
  5. Bao mat phan quyen cac endpoint kiem toan /api/compliance/* bang JWT.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models import Equipment, TelemetrySample
from app.services.compliance import (
    calculate_esg_carbon_footprint,
    VIETNAM_GRID_EMISSION_FACTOR,
)
from app.timeutil import utcnow


def test_haccp_audit_compliance_evaluation(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}
    session: Session = SessionLocal()
    try:
        eq = session.scalars(select(Equipment).where(Equipment.code == "KHO_DONG_01")).first()
        assert eq is not None

        # Nap 5 mau nhiet do an toan (<= -18 C)
        now = utcnow()
        for i in range(5):
            sample = TelemetrySample(
                equipment_id=eq.id,
                ts=now - timedelta(minutes=i * 10),
                temperature_c=-19.5 - (i * 0.2),
                status="RUNNING",
            )
            session.add(sample)
        session.commit()
    finally:
        session.close()

    res = seeded_client.get(f"/api/compliance/haccp/audit?equipment_id={eq.id}&hours=24", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert "standard" in data
    assert data["total_monitored_samples"] > 0
    assert "certificate_id" in data
    assert "certificate_signature" in data

    eq_audit = data["equipment_audits"][0]
    assert eq_audit["equipment_code"] == "KHO_DONG_01"
    assert eq_audit["haccp_limit_c"] == -18.0


def test_haccp_audit_detects_ccp_temperature_breach(seeded_client: TestClient, tokens: dict[str, str]):
    """Gia lap su co nhiet vuot -18C de kiem chung HACCP phat hien vi pham."""
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}
    session: Session = SessionLocal()
    try:
        eq = session.scalars(select(Equipment).where(Equipment.code == "KHO_DONG_02")).first()
        assert eq is not None

        now = utcnow()
        # Nap 1 mau vi pham nghiem trong (-15.2 C > -18.0 C)
        breach_sample = TelemetrySample(
            equipment_id=eq.id,
            ts=now - timedelta(minutes=5),
            temperature_c=-15.2,
            status="WARNING",
        )
        session.add(breach_sample)
        session.commit()
    finally:
        session.close()

    res = seeded_client.get(f"/api/compliance/haccp/audit?equipment_id={eq.id}&hours=1", headers=headers)
    assert res.status_code == 200
    data = res.json()

    eq_audit = data["equipment_audits"][0]
    assert eq_audit["breach_count"] >= 1
    assert eq_audit["max_temp_c"] >= -15.2
    assert eq_audit["verdict"] == "CRITICAL_LIMIT_BREACHED"
    assert eq_audit["is_compliant"] is False


def test_issue_haccp_certificate_api(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}

    payload = {
        "batch_name": "Lô cá tra phi lê đông lạnh xuất khẩu thị trường Nhật Bản",
        "auditor_notes": "Kiem toan vien Nguyen Van A - Tieu chuan TCVN 5603:2008",
        "hours": 24,
    }
    res = seeded_client.post("/api/compliance/haccp/certificate", json=payload, headers=headers)
    assert res.status_code == 200
    cert = res.json()

    assert cert["status"] == "ISSUED"
    assert cert["certificate_id"].startswith("CERT-HACCP-")
    assert cert["batch_name"] == payload["batch_name"]
    assert "signature_hash" in cert


def test_esg_carbon_footprint_calculation(seeded: Session):
    result = calculate_esg_carbon_footprint(seeded, days=30, refrigerant_leak_kg=5.0, refrigerant_code="R404A")

    assert result["reporting_period_days"] == 30
    assert result["grid_emission_factor_tco2_per_mwh"] == VIETNAM_GRID_EMISSION_FACTOR

    # 5.0 kg R404A * 3922 / 1000 = 19.61 tCO2e Scope 1
    assert result["refrigerant_loss_kg"] == 5.0
    assert result["scope_1_direct_tco2e"] == round(5.0 * 3922.0 / 1000.0, 3)

    assert result["scope_2_indirect_tco2e"] > 0
    assert result["total_emissions_tco2e"] > result["scope_1_direct_tco2e"]

    # Khong truyen kich ban -> bao cao noi thang "chua mo hinh hoa", khong tu gan 12%.
    assert result["ai_avoided_emissions_tco2e"] is None
    assert result["ai_avoided_basis"] == "NOT_MODELLED"

    scenario = calculate_esg_carbon_footprint(
        seeded, days=30, refrigerant_leak_kg=5.0, refrigerant_code="R404A", ai_saving_scenario_pct=12.0
    )
    assert scenario["ai_avoided_emissions_tco2e"] > 0
    assert scenario["ai_avoided_basis"] == "SCENARIO_PCT"
    assert scenario["ai_saving_scenario_pct"] == 12.0
    # Phat thai tranh duoc la con so tinh tu kich ban, khong duoc cong vao tong that.
    assert scenario["total_emissions_tco2e"] == result["total_emissions_tco2e"]


def test_esg_carbon_footprint_tu_choi_khi_thieu_moi_chat_hao_hut(seeded: Session):
    """R404A (GWP 3922) va R134a (GWP 1430) chenh nhau 2.7 lan - khong duoc tu chon."""
    with pytest.raises(ValueError, match="refrigerant_code"):
        calculate_esg_carbon_footprint(seeded, days=30, refrigerant_leak_kg=5.0)

    with pytest.raises(ValueError, match="GWP"):
        calculate_esg_carbon_footprint(seeded, days=30, refrigerant_leak_kg=5.0, refrigerant_code="R-999")


def test_get_esg_carbon_footprint_api(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['KETOAN']}"}
    res = seeded_client.get(
        "/api/compliance/esg/carbon-footprint?days=30&refrigerant_leak_kg=2.5&refrigerant_code=R404A",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()

    assert "scope_1_direct_tco2e" in data
    assert "scope_2_indirect_tco2e" in data
    assert "total_emissions_tco2e" in data
    assert data["refrigerant_loss_kg"] == 2.5


def test_get_esg_carbon_footprint_api_chan_khai_sai_moi_chat(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}

    # Co hao hut ma khong khai ma moi chat -> 400 kem danh sach doi xe that.
    missing = seeded_client.get(
        "/api/compliance/esg/carbon-footprint?days=30&refrigerant_leak_kg=2.5", headers=headers
    )
    assert missing.status_code == 400
    assert "R404A" in missing.json()["detail"]

    # Ma hop le nhung khong thiet bi nao trong doi xe dung -> 400, khong tinh ra so vo nghia.
    unused = seeded_client.get(
        "/api/compliance/esg/carbon-footprint?days=30&refrigerant_leak_kg=2.5&refrigerant_code=NH3",
        headers=headers,
    )
    assert unused.status_code == 400

    # Ma khong ton tai -> 400 (khong de ValueError lo ra thanh 500).
    bogus = seeded_client.get(
        "/api/compliance/esg/carbon-footprint?days=30&refrigerant_leak_kg=2.5&refrigerant_code=R-999",
        headers=headers,
    )
    assert bogus.status_code == 400
