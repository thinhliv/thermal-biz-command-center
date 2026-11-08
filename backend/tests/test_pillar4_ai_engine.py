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
from app.services.ai_energy import (
    HACCP_SAFETY_MARGIN_C,
    ISO_ZONE_A_MAX,
    ISO_ZONE_B_MAX,
    ISO_ZONE_C_MAX,
    PeakShavingConfigError,
    calculate_peak_shaving_plan,
    diagnose_predictive_maintenance,
)
from app.timeutil import utcnow


def test_calculate_peak_shaving_schedule_and_savings(seeded: Session):
    result = calculate_peak_shaving_plan(seeded, rated_power_kw=120.0, weekday=1)

    assert result["status"] == "active"
    assert result["daily_saving_vnd"] > 0
    assert result["monthly_saving_vnd"] > 0
    assert 30.0 <= result["peak_cost_reduction_pct"] <= 75.0

    # Don gia phai lay tu bang tariff_bands (seed 4586/2824/1808), khong phai hang so 3171 cu.
    assert result["peak_rate_vnd_per_kwh"] == 4586
    rates = {s["tariff_tier"]: s["rate_vnd_per_kwh"] for s in result["schedule"]}
    assert rates["PEAK"] == 4586
    assert rates["NORMAL"] == 2824
    assert rates["OFF_PEAK"] == 1808

    # Tien tiet kiem phai bang dung chech lech kWh x don gia that, khong phai con so viet tay.
    expected_saving = (
        result["baseline_peak_cost_vnd"]
        - result["shaved_peak_cost_vnd"]
        - result["pre_cool_extra_cost_vnd"]
    )
    assert result["daily_saving_vnd"] == expected_saving

    schedule = result["schedule"]
    assert len(schedule) == 9

    # Kiem tra co du cac pha quan trong
    phases = [s["phase"] for s in schedule]
    assert "PRE_COOL_1" in phases
    assert "PEAK_SHAVING_1" in phases
    assert "PRE_COOL_2" in phases
    assert "PEAK_SHAVING_2" in phases

    # Lich phai phu kin 24h va khong co khe ho khong co giay trung
    assert schedule[0]["start_minute"] == 0
    assert schedule[-1]["end_minute"] == 1440
    for previous, current in zip(schedule, schedule[1:]):
        assert previous["end_minute"] == current["start_minute"]

    # Moi khung cao diem deu phai co mot cua so lam lanh sau ngay truoc do
    for index, segment in enumerate(schedule):
        if segment["phase"].startswith("PEAK_SHAVING"):
            assert schedule[index - 1]["phase"].startswith("PRE_COOL")

    # Dam bao nhiet do muc tieu khong vi pham nguong HACCP (-18C) va con bien an toan
    ceiling = result["haccp_limit_c"] - HACCP_SAFETY_MARGIN_C
    assert result["haccp_limit_c"] == -18.0
    for s in schedule:
        assert s["target_temp_c"] <= -18.0
        assert s["target_temp_c"] <= ceiling

    # He so tai la gia thiet ky su -> phai duoc khai bao ro, khong duoc gia danh so lieu do
    assert result["assumptions"]["shaved_peak_load_pct"] == 22
    assert "khong phai so lieu do" in result["assumptions"]["note"]


def test_peak_shaving_plan_sunday_has_no_peak_hours(seeded: Session):
    """Chu nhat khong co gio cao diem theo bieu gia EVN -> khong duoc bia ra khoan tiet kiem."""
    result = calculate_peak_shaving_plan(seeded, rated_power_kw=120.0, weekday=7)

    assert result["status"] == "no_peak_hours"
    assert result["peak_hours_per_day"] == 0
    assert result["daily_saving_vnd"] == 0
    assert result["monthly_saving_vnd"] == 0
    assert result["peak_cost_reduction_pct"] == 0.0
    assert result["message"]
    assert not [s for s in result["schedule"] if s["phase"].startswith("PEAK_SHAVING")]
    # Van phu du 24h bang khung binh thuong / thap diem
    assert result["schedule"][0]["start_minute"] == 0
    assert result["schedule"][-1]["end_minute"] == 1440


def test_peak_shaving_plan_rejects_bad_inputs(seeded: Session):
    with pytest.raises(ValueError, match="lon hon 0"):
        calculate_peak_shaving_plan(seeded, rated_power_kw=0.0)
    with pytest.raises(ValueError, match="1..7"):
        calculate_peak_shaving_plan(seeded, weekday=8)
    # Lam lanh "sau" ma nong hon nhiet do van hanh thi khong tich duoc nhiet nao
    with pytest.raises(ValueError, match="thap hon"):
        calculate_peak_shaving_plan(seeded, base_temp_c=-18.0, pre_cool_target_c=-10.0)
    # Nguong HACCP la cua server: yeu cau van hanh nong hon nguong doi xe -> tu choi
    with pytest.raises(PeakShavingConfigError, match="HACCP"):
        calculate_peak_shaving_plan(seeded, base_temp_c=-5.0, pre_cool_target_c=-10.0)


def test_iso_10816_thresholds_pinned():
    """Neo dung nguong ISO 10816-3: doi nham mot con so la doi nham ca ket luan bao tri."""
    assert (ISO_ZONE_A_MAX, ISO_ZONE_B_MAX, ISO_ZONE_C_MAX) == (1.4, 2.8, 4.5)


def test_simulate_peak_shaving_api(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}

    payload = {
        "rated_power_kw": 250.0,
        "base_temp_c": -18.0,
        "pre_cool_target_c": -23.0,
        "weekday": 1,
    }
    res = seeded_client.post("/api/ai/peak-shaving/simulate", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["rated_power_kw"] == 250.0
    assert data["daily_saving_vnd"] > 1_000_000  # Voi 250kW tiet kiem tren 1 trieu VND/ngay


def test_simulate_peak_shaving_ignores_client_declared_haccp_limit(
    seeded_client: TestClient, tokens: dict[str, str]
):
    """Ben goi khai nguong HACCP -5C thi cung bi bo qua: day la thong so an toan cua server."""
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}
    payload = {
        "rated_power_kw": 120.0,
        "base_temp_c": -18.0,
        "pre_cool_target_c": -23.0,
        "haccp_limit_c": -5.0,  # truong nay khong con trong request model
    }
    res = seeded_client.post("/api/ai/peak-shaving/simulate", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["haccp_limit_c"] == -18.0
    assert data["safe_operating_ceiling_c"] == -18.5
    for segment in data["schedule"]:
        assert segment["target_temp_c"] <= -18.0


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
    # Con so phai la phep do that (3.8), khong phai gia tri "hop ly" dien vao khi thieu
    assert diag["vibration_mm_s"] == 3.8
    assert diag["vibration_measured_at"] is not None
    # COP thiet ke chi de so sanh, khong duoc thay the COP do duoc
    assert diag["cop_current"] == 3.2
    assert diag["design_cop"] != diag["cop_current"]


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
    # COP bao cao la gia tri do gan nhat (2.12), khong phai design_cop 3.6 cua ho so thiet bi
    assert diag["cop_current"] == 2.12
    assert diag["leak_severity"] == "CRITICAL"
    assert diag["cop_slope_unit"] == "COP per hour"
    assert diag["rul_basis"] == "COP_TREND"
    # RUL phai suy ra tu xu huong, khong phai con so 90 ngay mac dinh cu
    assert diag["estimated_rul_days"] is not None
    assert diag["estimated_rul_days"] != 90


def test_predictive_maintenance_khong_bia_so_lieu_khi_cam_bien_im_lang(seeded: Session):
    """Thieu rung / thieu COP thi bao "khong co so lieu", khong dien 1.2 mm/s hay COP 3.2."""
    eq = Equipment(
        code="MAY_NEN_CHUA_GAN_CAM_BIEN",
        name="Máy nén chưa gắn cảm biến",
        kind="COMPRESSOR",
        location="Nhà A",
        refrigerant="R404A",
        rated_power_kw=90.0,
        haccp_limit_c=-18.0,
        design_cop=3.4,
        is_active=True,
    )
    seeded.add(eq)
    seeded.flush()
    base_ts = utcnow() + timedelta(hours=1)
    for i in range(6):
        seeded.add(TelemetrySample(
            equipment_id=eq.id,
            ts=base_ts + timedelta(minutes=i),
            temperature_c=-19.0,
            status="RUNNING",
        ))
    seeded.commit()

    diag = diagnose_predictive_maintenance(seeded, equipment_id=eq.id)[0]

    assert diag["status"] == "DIAGNOSED"
    assert diag["vibration_mm_s"] is None
    assert diag["vibration_health"] == "NO_VIBRATION_DATA"
    assert diag["iso_zone"] is None
    assert diag["cop_current"] is None
    assert diag["cop_slope"] is None
    assert diag["refrigerant_leak_suspected"] is False
    assert diag["estimated_rul_days"] is None
    assert diag["rul_basis"] == "NOT_MODELLED"
    assert any("ISO 10816-3" in action for action in diag["recommended_actions"])


def test_predictive_maintenance_bao_no_data_khi_chua_co_telemetry(seeded: Session):
    eq = Equipment(
        code="KHO_DONG_MOI_LAP",
        name="Kho đông mới lắp",
        kind="DEEP_FREEZER",
        location="Nhà B",
        refrigerant="R404A",
        rated_power_kw=110.0,
        haccp_limit_c=-18.0,
        design_cop=3.7,
        is_active=True,
    )
    seeded.add(eq)
    seeded.commit()

    diag = diagnose_predictive_maintenance(seeded, equipment_id=eq.id)[0]

    assert diag["status"] == "NO_DATA"
    assert "vibration_mm_s" not in diag
    assert "cop_current" not in diag


def test_predictive_maintenance_lo_hoi_khong_bi_chan_doan_ro_ri_moi_chat(seeded: Session):
    """Lo hoi danh gia bang hieu suat eta: COP thap o day la loi dot, khong phai het gas."""
    boiler = seeded.scalars(select(Equipment).where(Equipment.code == "LO_HOI_01")).first()
    assert boiler is not None
    assert boiler.is_refrigeration is False

    base_ts = utcnow() + timedelta(hours=2)
    for i in range(6):
        seeded.add(TelemetrySample(
            equipment_id=boiler.id,
            ts=base_ts + timedelta(minutes=i),
            temperature_c=180.0,
            efficiency_pct=62.0,
            cop=1.1,  # so lieu nhieu ban, engine phai bo qua vi lo hoi khong dung COP
            status="RUNNING",
        ))
    seeded.commit()

    diag = diagnose_predictive_maintenance(seeded, equipment_id=boiler.id)[0]

    assert diag["refrigerant_leak_suspected"] is False
    assert diag["leak_severity"] == "NONE"
    assert diag["cop_slope"] is None
    assert diag["rul_basis"] == "NOT_MODELLED"
    assert not any("rò rỉ" in action for action in diag["recommended_actions"])


def test_predictive_maintenance_neu_dung_ten_moi_chat_cua_thiet_bi(seeded_client: TestClient, tokens: dict[str, str]):
    """CHILLER_01 chay R134a: bao cao phai noi R134a, khong duoc mac dinh R404A cua kho dong."""
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}
    session: Session = SessionLocal()
    try:
        eq = session.scalars(select(Equipment).where(Equipment.code == "CHILLER_01")).first()
        assert eq is not None
        assert eq.refrigerant == "R134a"

        now = utcnow()
        for i in range(6):
            session.add(TelemetrySample(
                equipment_id=eq.id,
                ts=now + timedelta(hours=3, minutes=i),
                temperature_c=4.0,
                vibration_mm_s=1.1,
                cop=2.2,
                status="RUNNING",
            ))
        session.commit()
    finally:
        session.close()

    res = seeded_client.get(f"/api/ai/predictive-maintenance/diagnostics?equipment_id={eq.id}", headers=headers)
    assert res.status_code == 200
    diag = res.json()[0]

    assert diag["refrigerant_leak_suspected"] is True
    assert any("R134a" in action for action in diag["recommended_actions"])
    assert not any("R404A" in action for action in diag["recommended_actions"])
