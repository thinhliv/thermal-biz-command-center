"""Chuan hoa dien nang theo nhiet do moi truong (IPMVP Option B/C Weather Normalization).

Vat ly nhiet lanh & Tieu chuan quoc te (EVO 10000-1:2012 / ASHRAE Guideline 14):
1. Phu tai nhiet truyen qua vo kho lanh tuan theo dinh luat Fourier:
     Q_envelope = U * A * (T_ambient - T_room)
   Tong nhiet truyen xuyen vo theo thoi gian ty le truc tiep voi do ngay lam lanh
   (Cooling Degree Days - CDD / Cooling Degree Hours - CDH).

2. Dan nong (condenser) giai nhiet ra khong khi ngoai troi:
     T_cond = T_ambient + Delta_T_approach
   Nhiet do moi truong tang lam ap suat ngung tu P_k tang, ti so nen tang,
   khien COP giam va dien nang tieu thu tren moi kW lanh tang manh (2% - 4% / deg C).

3. Quy tac bat buoc:
   - KHONG DUOC phep so sanh kWh truc tiep giua hai ky neu khong chuan hoa theo thoi tiet.
   - KHONG DUOC lay nhiet do buong bao quan (temperature_c trong TelemetrySample) lam
     proxy cho nhiet do ngoai troi: day la hai dai luong hoan toan khac nhau ve ban chat vat ly.
   - Thieu du lieu khi tuong thi he thong phai nem `InsufficientWeatherDataError`,
     tuyet doi khong bia so lieu hay am tham tra ve so 0.
   - Mo hinh hoi quy duong co so phai dat tieu chuan chap nhan cua IPMVP:
     R^2 >= 0.70 va CV(RMSE) <= 20% cho du lieu ngay (daily), hoac R^2 >= 0.75 va
     CV(RMSE) <= 15% cho du lieu thang (monthly). Neu khong dat, he thong phai cong bo
     ro rang trang thai khong dat va ly do tu choi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Equipment, OutdoorWeatherSample, Site, TelemetrySample


class InsufficientWeatherDataError(ValueError):
    """Nem ra khi thieu du lieu nhiet do moi truong do duoc."""
    pass


class InvalidBaselineDataError(ValueError):
    """Nem ra khi tap du lieu hoi quy khong hop le hoac qua it diem."""
    pass


# Tieu chuan chap nhan cua IPMVP / ASHRAE Guideline 14
IPMVP_DAILY_MIN_R2 = 0.70
IPMVP_DAILY_MAX_CV_RMSE_PCT = 20.0
IPMVP_MONTHLY_MIN_R2 = 0.75
IPMVP_MONTHLY_MAX_CV_RMSE_PCT = 15.0
IPMVP_MIN_DATA_POINTS = 5


@dataclass(frozen=True)
class WeatherBaselineModel:
    """Mo hinh hoi quy duong co so dien nang theo nhiet do moi truong / CDD."""
    slope: float  # beta_1: kWh / CDD
    intercept: float  # beta_0: kWh / ngay (phu tai nen khong phu thuoc thoi tiet)
    r_squared: float
    rmse: float
    cv_rmse_pct: float
    n_samples: int
    t_stat_slope: float
    is_ipmvp_valid: bool
    rejection_reason: Optional[str] = None
    assumptions: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WeatherNormalizedSavings:
    """Ket qua phan tich tiet kiem nang luong da chuan hoa theo thoi tiet."""
    baseline_days: int
    reporting_days: int
    base_temp_c: float
    baseline_cdd: float
    reporting_cdd: float
    baseline_actual_kwh: float
    reporting_actual_kwh: float
    adjusted_baseline_kwh: float
    normalized_savings_kwh: float
    normalized_savings_pct: float
    weather_effect_kwh: float
    unadjusted_savings_kwh: float
    baseline_model: WeatherBaselineModel
    is_savings_statistically_valid: bool
    explanation: str


def compute_cdd(temperatures_c: List[float], base_temp_c: float = 18.3) -> float:
    """Tinh tong do ngay lam lanh (Cooling Degree Days - CDD) tu chuoi nhiet do.

    Neu danh sach la chuoi theo gio (hourly samples):
      CDD = sum(max(0.0, T_h - T_base)) / 24.0
    Neu danh sach la chuoi nhiet do trung binh theo ngay (daily mean):
      CDD = sum(max(0.0, T_d - T_base))
    """
    if not temperatures_c:
        return 0.0
    cdd_sum = sum(max(0.0, t - base_temp_c) for t in temperatures_c)
    return round(cdd_sum / 24.0, 4)


def compute_daily_cdd(daily_mean_temp_c: float, base_temp_c: float = 18.3) -> float:
    """Tinh CDD cho 1 ngay dua tren nhiet do trung binh ngay."""
    return max(0.0, round(daily_mean_temp_c - base_temp_c, 4))


def fit_weather_baseline_model(
    data_points: List[Tuple[float, float]],
    granularity: str = "daily",
) -> WeatherBaselineModel:
    """Hoi quy tuyen tinh giua bien doc lap (CDD) va bien phu thuoc (kWh).

    Formula:
      Y = beta_0 + beta_1 * X
      where X = CDD, Y = Energy (kWh)

    Dung cong thuc thong ke tieu chuan cua IPMVP (EVO 10000-1:2012) va ASHRAE Guideline 14:
      - R^2: He so xac dinh
      - RMSE: Can bac hai sai so toan phan trung binh (Root Mean Square Error)
      - CV(RMSE): He so bien thien cua RMSE (%) = (RMSE / Y_mean) * 100
      - t_stat: t-statistic cua he so goc de xac nhan y nghia thong ke
    """
    n = len(data_points)
    if n < IPMVP_MIN_DATA_POINTS:
        raise InvalidBaselineDataError(
            f"Tap du lieu co so co {n} diem, khong du toi thieu {IPMVP_MIN_DATA_POINTS} diem "
            "de xay dung mo hinh hoi quy IPMVP co gia tri."
        )

    xs = [p[0] for p in data_points]  # CDD
    ys = [p[1] for p in data_points]  # kWh

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    s_xx = sum((x - mean_x) ** 2 for x in xs)
    s_yy = sum((y - mean_y) ** 2 for y in ys)
    s_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))

    if s_xx <= 1e-12:
        # Bien thoi tiet khong bien thien (tat ca cac ngay cung CDD) -> khong the hoi quy
        slope = 0.0
        intercept = mean_y
        ss_res = s_yy
        r_squared = 0.0
    else:
        slope = s_xy / s_xx
        intercept = mean_y - slope * mean_x
        ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
        r_squared = 1.0 - (ss_res / s_yy) if s_yy > 1e-12 else 0.0

    r_squared = max(0.0, min(1.0, r_squared))

    # Degrees of freedom = n - 2
    df = max(1, n - 2)
    s_e_squared = ss_res / df
    s_e = math.sqrt(s_e_squared)

    # RMSE theo dinh nghia ASHRAE: sqrt(ss_res / n)
    rmse = math.sqrt(ss_res / n)
    cv_rmse_pct = (rmse / mean_y * 100.0) if mean_y > 1e-6 else 0.0

    # t-statistic cua he so goc beta_1
    se_slope = math.sqrt(s_e_squared / s_xx) if s_xx > 1e-12 else 1e9
    t_stat_slope = (slope / se_slope) if se_slope > 1e-12 else 0.0

    # Kiem tra tieu chuan chap nhan IPMVP
    min_r2 = IPMVP_MONTHLY_MIN_R2 if granularity == "monthly" else IPMVP_DAILY_MIN_R2
    max_cv = IPMVP_MONTHLY_MAX_CV_RMSE_PCT if granularity == "monthly" else IPMVP_DAILY_MAX_CV_RMSE_PCT

    rejection_reasons = []
    if r_squared < min_r2:
        rejection_reasons.append(
            f"R^2 ({r_squared:.3f}) thap hon nguong toi thieu cua IPMVP ({min_r2:.2f})"
        )
    if cv_rmse_pct > max_cv:
        rejection_reasons.append(
            f"CV(RMSE) ({cv_rmse_pct:.1f}%) vuot qua nguong cho phep cua IPMVP ({max_cv:.1f}%)"
        )
    if t_stat_slope < 2.0 and s_xx > 1e-12:
        rejection_reasons.append(
            f"t-statistic cua he so doc ({t_stat_slope:.2f}) < 2.0 (khong co y nghia thong ke o muc tin cay 95%)"
        )

    is_valid = len(rejection_reasons) == 0
    rejection_str = "; ".join(rejection_reasons) if rejection_reasons else None

    assumptions = {
        "standard": "IPMVP EVO 10000-1:2012 / ASHRAE Guideline 14",
        "granularity": granularity,
        "min_r2_threshold": min_r2,
        "max_cv_rmse_pct_threshold": max_cv,
        "degrees_of_freedom": df,
        "standard_error_estimate": round(s_e, 3),
        "standard_error_slope": round(se_slope, 4),
    }

    return WeatherBaselineModel(
        slope=round(slope, 4),
        intercept=round(intercept, 4),
        r_squared=round(r_squared, 4),
        rmse=round(rmse, 4),
        cv_rmse_pct=round(cv_rmse_pct, 2),
        n_samples=n,
        t_stat_slope=round(t_stat_slope, 3),
        is_ipmvp_valid=is_valid,
        rejection_reason=rejection_str,
        assumptions=assumptions,
    )


def normalize_and_calculate_savings(
    baseline_model: WeatherBaselineModel,
    reporting_days: int,
    reporting_cdd: float,
    reporting_actual_kwh: float,
    baseline_days: int,
    baseline_cdd: float,
    baseline_actual_kwh: float,
    base_temp_c: float = 18.3,
) -> WeatherNormalizedSavings:
    """Chuan hoa dien nang ky bao cao va tinh toan muc tiet kiem thuc su.

    IPMVP Avoided Energy Formula:
      E_adjusted_baseline = beta_0 * reporting_days + beta_1 * reporting_cdd
      Normalized Savings = E_adjusted_baseline - E_reporting_actual
      Weather Effect = E_baseline_actual * (reporting_days / baseline_days) - E_adjusted_baseline
      Unadjusted Savings = E_baseline_actual * (reporting_days / baseline_days) - E_reporting_actual
    """
    adjusted_baseline_kwh = baseline_model.intercept * reporting_days + baseline_model.slope * reporting_cdd
    normalized_savings_kwh = adjusted_baseline_kwh - reporting_actual_kwh

    normalized_savings_pct = (
        (normalized_savings_kwh / adjusted_baseline_kwh * 100.0)
        if adjusted_baseline_kwh > 1e-6
        else 0.0
    )

    baseline_scaled_kwh = baseline_actual_kwh * (reporting_days / max(1, baseline_days))
    unadjusted_savings_kwh = baseline_scaled_kwh - reporting_actual_kwh
    weather_effect_kwh = baseline_scaled_kwh - adjusted_baseline_kwh

    is_valid = baseline_model.is_ipmvp_valid and normalized_savings_kwh > 0

    if not baseline_model.is_ipmvp_valid:
        explanation = (
            f"Mo hinh duong co so KHONG dat tieu chuan IPMVP ({baseline_model.rejection_reason}). "
            "Con so tiet kiem khong co gia tri phap ly de thanh toan ESCO."
        )
    elif normalized_savings_kwh <= 0:
        explanation = (
            f"Sau khi chuan hoa thoi tiet, ky bao cao tieu thu vuot muc duong co so "
            f"({abs(normalized_savings_kwh):.1f} kWh). Khong co tiet kiem thuc su."
        )
    else:
        explanation = (
            f"Tiet kiem chuan hoa thoi tiet dat {normalized_savings_kwh:.1f} kWh ({normalized_savings_pct:.2f}%). "
            f"Tac dong thoi tiet gay chenh lech {weather_effect_kwh:.1f} kWh."
        )

    return WeatherNormalizedSavings(
        baseline_days=baseline_days,
        reporting_days=reporting_days,
        base_temp_c=base_temp_c,
        baseline_cdd=round(baseline_cdd, 2),
        reporting_cdd=round(reporting_cdd, 2),
        baseline_actual_kwh=round(baseline_actual_kwh, 2),
        reporting_actual_kwh=round(reporting_actual_kwh, 2),
        adjusted_baseline_kwh=round(adjusted_baseline_kwh, 2),
        normalized_savings_kwh=round(normalized_savings_kwh, 2),
        normalized_savings_pct=round(normalized_savings_pct, 2),
        weather_effect_kwh=round(weather_effect_kwh, 2),
        unadjusted_savings_kwh=round(unadjusted_savings_kwh, 2),
        baseline_model=baseline_model,
        is_savings_statistically_valid=is_valid,
        explanation=explanation,
    )


def carnot_ambient_lift_penalty(
    evap_temp_c: float,
    ambient_temp_c: float,
    condenser_approach_k: float = 8.0,
    reference_ambient_c: float = 30.0,
) -> Dict[str, Any]:
    """Tinh do suy giam COP Carnot va phat sinh cong suat do nhiet do moi truong tang cao.

    Dan nong giai nhiet khong khi:
      T_cond = T_ambient + condenser_approach_k
    Carnot COP = (T_evap + 273.15) / (T_cond - T_evap)

    Moi khi nhiet do moi truong tang 1 deg C, T_cond tang 1 deg C, khien COP Carnot sut giam
    va may nen tieu thu dien nang nhieu hon.
    """
    if ambient_temp_c <= evap_temp_c:
        raise ValueError("Nhiet do moi truong phai cao hon nhiet do bay hoi.")

    t_evap_k = evap_temp_c + 273.15

    # Nhiet do ngung tu thuc te
    t_cond_actual_c = ambient_temp_c + condenser_approach_k
    t_cond_actual_k = t_cond_actual_c + 273.15
    cop_carnot_actual = t_evap_k / (t_cond_actual_k - t_evap_k)

    # Nhiet do ngung tu o moc tham chieu chuan (VD: 30 deg C)
    t_cond_ref_c = reference_ambient_c + condenser_approach_k
    t_cond_ref_k = t_cond_ref_c + 273.15
    cop_carnot_ref = t_evap_k / (t_cond_ref_k - t_evap_k)

    # Ty le chenh lech cong suat may nen (% cong suat phat sinh them so voi moc tham chieu)
    # W = Q / COP => W_actual / W_ref = COP_ref / COP_actual
    power_penalty_pct = (
        ((cop_carnot_ref - cop_carnot_actual) / cop_carnot_actual) * 100.0
        if cop_carnot_actual > 0
        else 0.0
    )

    return {
        "evap_temp_c": evap_temp_c,
        "ambient_temp_c": ambient_temp_c,
        "condenser_approach_k": condenser_approach_k,
        "reference_ambient_c": reference_ambient_c,
        "t_cond_actual_c": round(t_cond_actual_c, 2),
        "cop_carnot_actual": round(cop_carnot_actual, 3),
        "cop_carnot_ref": round(cop_carnot_ref, 3),
        "power_penalty_pct": round(power_penalty_pct, 2),
        "explanation": (
            f"Nhiet do ngoai troi {ambient_temp_c:.1f} C (so voi moc {reference_ambient_c:.1f} C) "
            f"day nhiet do ngung tu len {t_cond_actual_c:.1f} C, khien COP Carnot sut tu "
            f"{cop_carnot_ref:.2f} xuong {cop_carnot_actual:.2f}, lam may nen ton them "
            f"{power_penalty_pct:.1f}% dien nang."
        ),
    }


def get_site_weather_samples(
    session: Session,
    site_id: int,
    start_ts: datetime,
    end_ts: datetime,
) -> List[OutdoorWeatherSample]:
    """Lay danh sach mau do nhiet do ngoai troi thuc te cua co so.

    QUY TAC BAT BUOC:
    - Chi doc tu bang `outdoor_weather_samples`.
    - KHONG duoc phep fallback sang `TelemetrySample.temperature_c` vi do la nhiet do buong/san pham.
    - Neu khong co ban ghi nao, nem `InsufficientWeatherDataError` de caller xu ly nghiem ngat.
    """
    stmt = (
        select(OutdoorWeatherSample)
        .where(
            OutdoorWeatherSample.site_id == site_id,
            OutdoorWeatherSample.ts >= start_ts,
            OutdoorWeatherSample.ts <= end_ts,
        )
        .order_by(OutdoorWeatherSample.ts.asc())
    )
    samples = list(session.scalars(stmt))
    if not samples:
        site = session.get(Site, site_id)
        site_name = site.name if site else f"ID {site_id}"
        raise InsufficientWeatherDataError(
            f"Khong co du lieu nhiet do moi truong ngoai troi cho co so '{site_name}' "
            f"trong khoang {start_ts.isoformat()} -> {end_ts.isoformat()}. "
            "Theo tieu chuan IPMVP, nghiem cam lay nhiet do buong bao quan lam proxy cho moi truong!"
        )
    return samples
