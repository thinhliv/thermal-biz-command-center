"""Kiem thu nghiem ngat Chuan hoa dien nang theo nhiet do moi truong (IPMVP Option B/C).

Bao phu:
- Tinh do ngay lam lanh (Cooling Degree Days - CDD) theo gio va theo ngay.
- Hoi quy tuyen tinh duong co so nang luong (IPMVP Option B/C, EVO 10000-1:2012).
- Tieu chuan chap nhan IPMVP: R^2 >= 0.70, CV(RMSE) <= 20%, t-statistic >= 2.0.
- Phan tach tac dong thoi tiet (Weather Effect) khoi tiet kiem ky thuat thuc su (Normalized Savings).
- Ton that Carnot lift do nhiet do moi truong nong day T_cond len cao.
- Quy tac cam nguy tao: tu choi dung nhiet do buong/san pham lam proxy cho moi truong.
- Cac API endpoint cua /api/weather/* kem phan quyen.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutdoorWeatherSample, Site, User
from app.services.weather_normalization import (
    IPMVP_DAILY_MAX_CV_RMSE_PCT,
    IPMVP_DAILY_MIN_R2,
    InsufficientWeatherDataError,
    InvalidBaselineDataError,
    WeatherBaselineModel,
    carnot_ambient_lift_penalty,
    compute_cdd,
    compute_daily_cdd,
    fit_weather_baseline_model,
    get_site_weather_samples,
    normalize_and_calculate_savings,
)
from app.timeutil import utcnow


# --------------------------------------------------------------------------- #
# CDD Tests
# --------------------------------------------------------------------------- #
def test_compute_daily_cdd():
    # 32 C trung binh ngay, base 18.3 C => 13.7 CDD
    assert compute_daily_cdd(32.0, base_temp_c=18.3) == pytest.approx(13.7, abs=1e-3)
    # 15 C (lanh hon base 18.3 C) => 0 CDD (khong phat sinh tai lanh do thoi tiet ngoai)
    assert compute_daily_cdd(15.0, base_temp_c=18.3) == 0.0


def test_compute_cdd_from_hourly_temperatures():
    # 24 gio deu 28.3 C, base 18.3 C => moi gio chenh 10 C => CDD = (24 * 10) / 24 = 10.0
    hourly = [28.3] * 24
    assert compute_cdd(hourly, base_temp_c=18.3) == pytest.approx(10.0, abs=1e-3)

    # Nua ngay 18.3 C, nua ngay 30.3 C => (12 * 0 + 12 * 12) / 24 = 6.0
    mixed = [18.3] * 12 + [30.3] * 12
    assert compute_cdd(mixed, base_temp_c=18.3) == pytest.approx(6.0, abs=1e-3)


# --------------------------------------------------------------------------- #
# IPMVP Regression Baseline Model Tests
# --------------------------------------------------------------------------- #
def test_fit_weather_baseline_model_passes_ipmvp_standards():
    """Duong co so chuan: dien nang tang theo CDD (slope ~ 50 kWh/CDD, base 200 kWh/ngay)."""
    # Sinh 20 ngay co so voi tuong quan thoi tiet manh
    data = []
    for day in range(20):
        cdd = 8.0 + (day % 10) * 1.2  # CDD tu 8.0 den 18.8
        # Y = 200 + 50 * cdd + nhiễu nhỏ
        kwh = 200.0 + 50.0 * cdd + (day % 3 - 1) * 5.0
        data.append((cdd, kwh))

    model = fit_weather_baseline_model(data, granularity="daily")

    assert model.slope == pytest.approx(50.0, abs=2.0)
    assert model.intercept == pytest.approx(200.0, abs=15.0)
    assert model.r_squared >= IPMVP_DAILY_MIN_R2
    assert model.cv_rmse_pct <= IPMVP_DAILY_MAX_CV_RMSE_PCT
    assert model.t_stat_slope >= 2.0
    assert model.is_ipmvp_valid is True
    assert model.rejection_reason is None
    assert model.assumptions["standard"] == "IPMVP EVO 10000-1:2012 / ASHRAE Guideline 14"


def test_fit_weather_baseline_model_fails_when_r2_too_low():
    """Du lieu nhieu loan, khong tuong quan voi CDD => IPMVP tu choi mo hinh."""
    data = [
        (10.0, 500.0),
        (12.0, 200.0),
        (8.0, 600.0),
        (15.0, 150.0),
        (11.0, 480.0),
        (14.0, 210.0),
        (9.0, 550.0),
        (13.0, 180.0),
    ]
    model = fit_weather_baseline_model(data, granularity="daily")
    assert model.is_ipmvp_valid is False
    assert model.rejection_reason is not None
    assert "R^2" in model.rejection_reason or "t-statistic" in model.rejection_reason


def test_fit_weather_baseline_model_raises_on_insufficient_samples():
    """It hon 5 diem du lieu khong du de lap duong co so."""
    data = [(10.0, 500.0), (12.0, 600.0), (14.0, 700.0)]
    with pytest.raises(InvalidBaselineDataError) as exc_info:
        fit_weather_baseline_model(data)
    assert "khong du toi thieu" in str(exc_info.value)


# --------------------------------------------------------------------------- #
# Savings Normalization & Decomposition Tests
# --------------------------------------------------------------------------- #
def test_savings_decomposition_hotter_weather():
    """Ky bao cao nong hon ky co so, nhung he thong van tiet kiem:

    Ky co so: 30 ngay, CDD = 300, tieu thu 18,000 kWh.
    Ky bao cao: 30 ngay, CDD = 450 (nong hon 50%), thuc te tieu thu 19,000 kWh.
    Neu so sanh don thuan: 18,000 - 19,000 = -1,000 kWh (tuong la lang phi!).
    Nhung theo duong co so:
      E_adjusted = intercept * 30 + slope * 450 = 22,500 kWh.
      Tiet kiem thuc: 22,500 - 19,000 = +3,500 kWh (+15.5%)!
    """
    model = WeatherBaselineModel(
        slope=30.0,  # 30 kWh / CDD
        intercept=300.0,  # 300 kWh / ngay
        r_squared=0.88,
        rmse=15.0,
        cv_rmse_pct=4.2,
        n_samples=30,
        t_stat_slope=12.5,
        is_ipmvp_valid=True,
    )

    res = normalize_and_calculate_savings(
        baseline_model=model,
        reporting_days=30,
        reporting_cdd=450.0,
        reporting_actual_kwh=19000.0,
        baseline_days=30,
        baseline_cdd=300.0,
        baseline_actual_kwh=18000.0,
        base_temp_c=18.3,
    )

    # adjusted = 300 * 30 + 30 * 450 = 9,000 + 13,500 = 22,500 kWh
    assert res.adjusted_baseline_kwh == 22500.0
    # Tiet kiem chuan hoa thoi tiet = 22,500 - 19,000 = 3,500 kWh
    assert res.normalized_savings_kwh == 3500.0
    assert res.normalized_savings_pct == pytest.approx(15.56, abs=0.05)
    # So sanh tho (unadjusted): 18,000 - 19,000 = -1,000 kWh
    assert res.unadjusted_savings_kwh == -1000.0
    # Tac dong thoi tiet: 18,000 - 22,500 = -4,500 kWh
    assert res.weather_effect_kwh == -4500.0
    # Tong unadjusted = normalized + weather_effect (-1000 = 3500 + (-4500))
    assert res.unadjusted_savings_kwh == pytest.approx(
        res.normalized_savings_kwh + res.weather_effect_kwh, abs=1e-2
    )
    assert res.is_savings_statistically_valid is True


# --------------------------------------------------------------------------- #
# Carnot Ambient Lift Penalty Tests
# --------------------------------------------------------------------------- #
def test_carnot_ambient_lift_penalty_calculation():
    """Khi nhiet do ngoai troi tang tu 30 C len 40 C:

    Bay hoi -25 C. Condenser approach = 8 K.
    O 30 C: T_cond = 38 C (311.15 K), COP_Carnot = 248.15 / (311.15 - 248.15) = 3.939
    O 40 C: T_cond = 48 C (321.15 K), COP_Carnot = 248.15 / (321.15 - 248.15) = 3.399
    Ton that cong suat may nen: (3.939 - 3.399) / 3.399 * 100 ~ +15.9%
    """
    res = carnot_ambient_lift_penalty(
        evap_temp_c=-25.0,
        ambient_temp_c=40.0,
        condenser_approach_k=8.0,
        reference_ambient_c=30.0,
    )

    assert res["t_cond_actual_c"] == 48.0
    assert res["cop_carnot_ref"] == pytest.approx(3.939, abs=0.01)
    assert res["cop_carnot_actual"] == pytest.approx(3.399, abs=0.01)
    assert res["power_penalty_pct"] > 15.0
    assert "ton them" in res["explanation"]


def test_carnot_ambient_lift_penalty_rejects_evap_above_ambient():
    with pytest.raises(ValueError):
        carnot_ambient_lift_penalty(evap_temp_c=35.0, ambient_temp_c=30.0)


# --------------------------------------------------------------------------- #
# Data Provenance & Anti-Cheating Tests
# --------------------------------------------------------------------------- #
def test_get_site_weather_samples_strictly_refuses_to_guess_when_no_records(seeded: Session):
    """Neu co so khong co sensor thoi tiet ngoai troi thi phai bao loi,

    NGHIEM CAM lay nhiet do buong/san pham de lam proxy.
    """
    site = seeded.scalars(select(Site)).first()
    assert site is not None

    future_start = utcnow() + timedelta(days=100)
    future_end = future_start + timedelta(days=5)

    with pytest.raises(InsufficientWeatherDataError) as exc_info:
        get_site_weather_samples(seeded, site.id, future_start, future_end)

    assert "nghiem cam" in str(exc_info.value).lower()
    assert "proxy" in str(exc_info.value).lower()


# --------------------------------------------------------------------------- #
# API Endpoint Tests
# --------------------------------------------------------------------------- #
def test_weather_endpoints_work_with_auth(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['VANHANH']}"}

    # 1. Ingest sample
    now_iso = utcnow().isoformat()
    ingest_payload = {
        "site_code": "SITE-NHA-A",
        "ts": now_iso,
        "ambient_temperature_c": 32.5,
        "relative_humidity_pct": 68.0,
        "source": "ON_SITE_SENSOR",
        "station_id": "TEST-STATION-01",
        "is_measured": True,
    }
    resp = seeded_client.post("/api/weather/samples", json=ingest_payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["site_code"] == "SITE-NHA-A"
    assert data["ambient_temperature_c"] == 32.5

    # 2. Get samples
    resp2 = seeded_client.get("/api/weather/sites/SITE-NHA-A/samples", headers=headers)
    assert resp2.status_code == 200
    samples = resp2.json()
    assert len(samples) >= 1
    assert any(s["station_id"] == "TEST-STATION-01" for s in samples)

    # 3. Carnot lift endpoint
    resp3 = seeded_client.get(
        "/api/weather/carnot-lift?evap_temp_c=-25.0&ambient_temp_c=36.0",
        headers=headers,
    )
    assert resp3.status_code == 200
    lift_data = resp3.json()
    assert "power_penalty_pct" in lift_data
    assert lift_data["t_cond_actual_c"] == 44.0

    # 4. Normalize endpoint
    norm_payload = {
        "site_code": "SITE-NHA-A",
        "baseline_days": 10,
        "reporting_days": 10,
        "base_temp_c": 18.3,
        "baseline_cdd": 120.0,
        "reporting_cdd": 140.0,
        "baseline_actual_kwh": 5000.0,
        "reporting_actual_kwh": 4800.0,
        "baseline_daily_data": [
            [10.0, 480.0],
            [11.0, 495.0],
            [12.0, 510.0],
            [13.0, 525.0],
            [10.5, 488.0],
            [11.5, 502.0],
            [12.5, 518.0],
            [13.5, 532.0],
            [11.0, 496.0],
            [12.0, 512.0],
        ],
    }
    resp4 = seeded_client.post("/api/weather/normalize", json=norm_payload, headers=headers)
    assert resp4.status_code == 200
    norm_result = resp4.json()
    assert norm_result["site_code"] == "SITE-NHA-A"
    assert norm_result["normalized_savings_kwh"] > 0
    assert norm_result["is_savings_statistically_valid"] is True
