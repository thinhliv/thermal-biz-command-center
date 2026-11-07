"""Bo kiem thu Pillar 4: AI Peak-Shaving & Predictive Maintenance Engine.

Kiem chung:
  1. Thuat toan Peak-Shaving 24h dua tren quan tinh nhiet va bieu gia gio cao diem EVN.
  2. Uoc tinh tiet kiem chi phi dien (VND & %) va dam bao nguong an toan HACCP.
  3. Chan doan rung dong co khi theo tieu chuan ISO 10816-3 (Zone A, B, C, D).
  4. Phat hien ro ri moi chat lanh R404A dua tren do doc suy giam COP (COP degradation slope).
  5. Bao mat cac endpoint /api/ai/* bang JWT.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
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
from app.services.ai_energy import (
    calculate_peak_shaving_plan,
    diagnose_predictive_maintenance,
    ISO_ZONE_A_MAX,
    ISO_ZONE_B_MAX,
    ISO_ZONE_C_MAX,
)
from app.timeutil import utcnow


def test_calculate_peak_shaving_schedule_and_savings():
    result = calculate_peak_shaving_plan(rated_power_kw=120.0)

    assert result["status"] == "active"
    assert result["daily_saving_vnd"] > 0
    assert result["monthly_saving_vnd"] > 0
    assert 30.0 <= result["peak_cost_reduction_pct"] <= 75.0

    schedule = result["schedule"]
    assert len(schedule) == 9

    # Kiem tra co du cac pha quan trong
    phases = [s["phase"] for s in schedule]
    assert "PRE_COOL_1" in phases
    assert "PEAK_SHAVING_1" in phases
    assert "PRE_COOL_2" in phases
    assert "PEAK_SHAVING_2" in phases

    # Dam bao nhiet do muc tieu khong vi pham nguong HACCP (-18C)
    for s in schedule:
        assert s["target_temp_c"] <= -18.0


def test_simulate_peak_shaving_api(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}

    payload = {
        "rated_power_kw": 250.0,
        "base_temp_c": -18.0,
        "pre_cool_target_c": -23.0,
        "haccp_limit_c": -18.0,
    }
    res = seeded_client.post("/api/ai/peak-shaving/simulate", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["rated_power_kw"] == 250.0
    assert data["daily_saving_vnd"] > 1_000_000  # Voi 250kW tiet kiem tren 1 trieu VND/ngay


def test_get_peak_shaving_schedule_api(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['VANHANH']}"}
    res = seeded_client.get("/api/ai/peak-shaving/schedule", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "schedule" in data
    assert "daily_saving_vnd" in data


def test_predictive_maintenance_iso10816_zones(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}
    session: Session = SessionLocal()
    try:
        # Tim mot thiet bi may nen hoac kho dong
        eq = session.scalars(select(Equipment).where(Equipment.code == "MAY_NEN_01")).first()
        assert eq is not None

        # Nap mot mau co rung dong Zone C (3.8 mm/s)
        sample = TelemetrySample(
            equipment_id=eq.id,
            ts=utcnow() + timedelta(seconds=1),
            temperature_c=-25.0,
            vibration_mm_s=3.8,
            cop=3.2,
            status="RUNNING",
        )
        session.add(sample)
        session.commit()
    finally:
        session.close()

    res = seeded_client.get("/api/ai/predictive-maintenance/diagnostics?equipment_id=" + str(eq.id), headers=headers)
    assert res.status_code == 200
    diagnostics = res.json()
    assert len(diagnostics) == 1
    diag = diagnostics[0]

    assert diag["equipment_code"] == "MAY_NEN_01"
    assert diag["iso_zone"] == "ZONE_C"
    assert diag["vibration_health"] == "WARNING"
    assert any("30 ngày" in action for action in diag["recommended_actions"])


def test_predictive_maintenance_cop_degradation_and_leak_detection(seeded_client: TestClient, tokens: dict[str, str]):
    """Gia lap chuoi COP suy giam lien tuc de kiem chung AI phat hien ro ri R404A."""
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}
    session: Session = SessionLocal()
    try:
        eq = session.scalars(select(Equipment).where(Equipment.code == "KHO_DONG_01")).first()
        assert eq is not None

        now = utcnow()
        # Tao chuoi 10 mau tuong lai gan voi COP giam dan tu 3.2 xuong 2.12 (suy thoai nghiem trong)
        for i in range(10):
            sample = TelemetrySample(
                equipment_id=eq.id,
                ts=now + timedelta(minutes=i + 1),
                temperature_c=-19.0,
                vibration_mm_s=1.5,
                cop=3.2 - (i * 0.12),
                status="RUNNING",
            )
            session.add(sample)
        session.commit()
    finally:
        session.close()

    res = seeded_client.get(f"/api/ai/predictive-maintenance/diagnostics?equipment_id={eq.id}", headers=headers)
    assert res.status_code == 200
    diag = res.json()[0]

    assert diag["refrigerant_leak_suspected"] is True
    assert diag["cop_slope"] < 0
    assert any("R404A" in action for action in diag["recommended_actions"])
