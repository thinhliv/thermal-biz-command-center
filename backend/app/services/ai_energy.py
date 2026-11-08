"""Engine Toi uu Nang luong Dinh (AI Peak-Shaving) va Bao tri Du doan (Predictive Maintenance).

1. Peak-Shaving Schedule:
   - Lich 24h DUOC SUY RA TU BANG `tariff_bands`: khung gio cao diem va don gia la quyet dinh cua
     EVN, khong phai hang so trong ma nguon. EVN doi gio hay doi gia thi lich tu doi theo, khong
     con canh hai noi khai hai kieu (truoc day module nay dat gia 3171/1685/1100 trong khi bang
     gia that la 4586/2824/1808 -> bao cao tiet kiem lech gan 45%).
   - Pre-cooling: ha nhiet do kho xuong truoc moi khung gio cao diem de nap "quan tinh nhiet" vao
     hang hoa, sau do tiet giam tai may nen trong khung gio dat do.
   - Moi nhiet do muc tieu deu bi chan duoi nguong HACCP cua doi xe (server tu lay tu bang
     equipment) tru them mot bien an toan. KHONG nhan nguong HACCP tu ben goi: client khai -5 C
     thi ke hoach "cat dinh" hoa ra ke hoach lam hong hang thuy san.

2. Predictive Maintenance (PdM):
   - Do rung co khi theo tieu chuan ISO 10816-3 (Zone A/B/C/D).
   - Do doc suy giam COP hoi quy theo THOI GIAN THAT (gio), khong theo chi so mau: mau cach nhau
     15 phut ma tinh nhu cach nhau 1 gio thi toc do suy thoai bi thoi phong gap 4 lan.
   - Thieu so lieu thi bao NO_DATA / NO_VIBRATION_DATA. KHONG dien mot gia tri "hop ly" thay cho
     cam bien: mot con so trung binh nam trong ma nguon nhin giong het mot phep do va se duoc
     tin nhu the (cu: `latest.vibration_mm_s or 1.2`, `latest.cop or design_cop or 3.2`,
     `rul_days = 90`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import (
    REFRIGERATION_KINDS,
    Equipment,
    TariffBand,
    TariffBandCode,
    TelemetrySample,
)
from ..timeutil import utctoday, utcnow
from . import billing

# Nguong rung ISO 10816-3 (mm/s)
ISO_ZONE_A_MAX = 1.4  # Tuyen hao
ISO_ZONE_B_MAX = 2.8  # Van hanh binh thuong
ISO_ZONE_C_MAX = 4.5  # Canh bao - can len ke hoach sua chua

#: Cac loai thiet bi duoc danh gia bang COP. Lo hoi dung hieu suat eta nen khong thuoc nhom nay.
REFRIGERATION_KIND_VALUES = sorted(k.value for k in REFRIGERATION_KINDS)

#: Bien an toan bat buoc giua nhiet do muc tieu va nguong HACCP. Cat dinh ma de nhiet do troi
#: dung bang nguong thi mot nhiet ke lech chut xiu cung thanh vi pham HACCP.
HACCP_SAFETY_MARGIN_C = 0.5

#: So phut lam lanh sau truoc moi khung gio cao diem.
PRE_COOL_MINUTES = 120

# Cac he so tai duoi day la PHUONG AN van hanh do ky su chon, khong phai so lieu do duoc.
# Chung duoc tra ve trong `assumptions` de nguoi doc bao cao biet dau la gia thiet.
BASELINE_PEAK_LOAD_PCT = 80  # neu khong cat dinh, may nen chay bao nhieu % trong gio cao diem
SHAVED_PEAK_LOAD_PCT = 22  # muc tai giu lai khi da cat dinh
PRE_COOL_EXTRA_LOAD_PCT = 35  # phan tai keo them trong luc lam lanh sau
MAINTAIN_LOAD_PCT = 60  # tai duy tri ngoai gio cao diem

TIER_LABELS = {
    TariffBandCode.PEAK.value: "Giờ cao điểm",
    TariffBandCode.NORMAL.value: "Giờ bình thường",
    TariffBandCode.OFF_PEAK.value: "Giờ thấp điểm",
}

# Chan doan COP
COP_FAILURE_THRESHOLD = 2.0  # duoi muc nay coi nhu mat kha nang lam lanh theo yeu cau
COP_LEAK_ABSOLUTE = 2.5  # COP tuyen doi thap -> nghi ngo ro ri moi chat
COP_CRITICAL_ABSOLUTE = 2.3
COP_LEAK_SLOPE_PER_DAY = -0.05  # sut qua 0.05 COP/ngay la suy thoai that su
MIN_SAMPLES_FOR_TREND = 5
TREND_SAMPLE_LIMIT = 50


class PeakShavingConfigError(ValueError):
    """Thieu cau hinh phia server de lap ke hoach cat dinh an toan.

    Tach rieng khoi ValueError de router co the tra 400 "he thong chua duoc cau hinh" thay vi
    lan voi 400 "nguoi goi truyen tham so sai".
    """


def _linear_slope(xs: List[float], ys: List[float]) -> Optional[float]:
    """Hoi quy tuyen tinh binh phuong toi thieu; None khi khong du diem hoac trung hoanh do."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    numer = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
    return numer / denom


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def fleet_haccp_limit_c(session: Session) -> Optional[float]:
    """Nguong HACCP chat nhat cua doi xe lanh dang hoat dong.

    Lay MIN vi mot lich dieu phoi dung chung cho ca doi xe: chi can mot asset bat buoc -18 C thi
    toan bo ke hoach khong duoc phep troi qua -18 C. Tra ve None khi khong asset nao khai nguong.
    """
    limits = session.scalars(
        select(Equipment.haccp_limit_c).where(
            Equipment.is_active.is_(True),
            Equipment.haccp_limit_c.is_not(None),
            Equipment.kind.in_(REFRIGERATION_KIND_VALUES),
        )
    ).all()
    return min(limits) if limits else None


def weekday_segments(bands: List[TariffBand], weekday: int) -> List[Tuple[int, int, str, int]]:
    """Cac khoang (start, end, ma khung gio, don gia) cua mot ngay ISO 1..7.

    Gop cac khoang lien tiep cung ma va cung gia thanh mot doan de lich doc giong bang gia that.
    """
    segments: List[Tuple[int, int, str, int]] = []
    for band in bands:
        if band.days == "*":
            allowed = None
        else:
            allowed = {int(d) for d in band.days.split(",") if d.strip()}
            if weekday not in allowed:
                continue
        if band.end_minute <= band.start_minute:
            continue
        segments.append((band.start_minute, band.end_minute, band.code, int(band.price_vnd_per_kwh)))

    segments.sort(key=lambda s: (s[0], s[1]))
    merged: List[Tuple[int, int, str, int]] = []
    for start, end, code, price in segments:
        if merged and merged[-1][2] == code and merged[-1][3] == price and merged[-1][1] == start:
            merged[-1] = (merged[-1][0], end, code, price)
        else:
            merged.append((start, end, code, price))
    return merged


def _insert_pre_cool_windows(
    segments: List[Tuple[int, int, str, int]],
) -> List[Tuple[int, int, str, int, bool]]:
    """Tach PRE_COOL_MINUTES cuoi cua khung gio lien truoc moi khung cao diem.

    Chi tach khi doan truoc do dai hon cua so pre-cool, neu khong se sinh ra mot pha am phut.
    """
    peak_code = TariffBandCode.PEAK.value
    out: List[Tuple[int, int, str, int, bool]] = []
    for index, (start, end, code, price) in enumerate(segments):
        next_is_peak = index + 1 < len(segments) and segments[index + 1][2] == peak_code
        if next_is_peak and code != peak_code and (end - start) > PRE_COOL_MINUTES:
            split_at = end - PRE_COOL_MINUTES
            out.append((start, split_at, code, price, False))
            out.append((split_at, end, code, price, True))
        else:
            out.append((start, end, code, price, False))
    return out


def build_peak_shaving_schedule(
    segments: List[Tuple[int, int, str, int]],
    base_temp_c: float,
    pre_cool_target_c: float,
    safe_ceiling_c: float,
) -> List[Dict[str, Any]]:
    """Bien doi cac khoang gia dien thanh lich van hanh, moi nhiet do deu <= safe_ceiling_c."""
    peak_code = TariffBandCode.PEAK.value
    maintain_target_c = min(base_temp_c, safe_ceiling_c)
    pre_cool_command_c = min(pre_cool_target_c, safe_ceiling_c)

    phases: List[Dict[str, Any]] = []
    pre_cool_seq = 0
    peak_seq = 0
    for start, end, code, price, is_pre_cool in _insert_pre_cool_windows(segments):
        if is_pre_cool:
            pre_cool_seq += 1
            phase = f"PRE_COOL_{pre_cool_seq}"
            phase_name = f"Làm lạnh sâu đợt {pre_cool_seq} (Pre-cooling)"
            load_pct = MAINTAIN_LOAD_PCT + PRE_COOL_EXTRA_LOAD_PCT
            target_c = pre_cool_command_c
            description = "Tích trữ năng lượng nhiệt vào sản phẩm trước giờ cao điểm"
        elif code == peak_code:
            peak_seq += 1
            phase = f"PEAK_SHAVING_{peak_seq}"
            phase_name = f"Cắt đỉnh đợt {peak_seq} (Peak-Shaving)"
            load_pct = SHAVED_PEAK_LOAD_PCT
            target_c = safe_ceiling_c
            description = (
                f"Tiết giảm tải máy nén xuống {load_pct}%; nhiệt độ được phép trôi lên "
                f"{target_c:.1f}°C, vẫn dưới ngưỡng HACCP "
                f"{safe_ceiling_c + HACCP_SAFETY_MARGIN_C:.1f}°C"
            )
        else:
            label = TIER_LABELS.get(code, code).lower()
            phase = f"{code}_MAINTAIN"
            phase_name = f"Duy trì {label}"
            load_pct = MAINTAIN_LOAD_PCT
            target_c = maintain_target_c
            description = f"Vận hành ổn định theo {label}"

        phases.append({
            "period": f"{_hhmm(start)} - {_hhmm(end)}",
            "start_minute": start,
            "end_minute": end,
            "duration_hours": round((end - start) / 60.0, 3),
            "phase": phase,
            "phase_name": phase_name,
            "compressor_load_pct": load_pct,
            "target_temp_c": round(target_c, 2),
            "tariff_tier": code,
            "rate_vnd_per_kwh": price,
            "description": description,
        })
    return phases


def calculate_peak_shaving_plan(
    session: Session,
    rated_power_kw: float = 120.0,
    base_temp_c: float = -18.0,
    pre_cool_target_c: float = -22.5,
    weekday: int = 1,
) -> Dict[str, Any]:
    """Lap ke hoach dieu phoi phu tai 24h cho mot ngay ISO (1 = thu Hai .. 7 = chu nhat).

    Raises:
        ValueError: tham so nguoi goi truyen vao vo ly.
        PeakShavingConfigError: server thieu bieu gia hoac thieu nguong HACCP -> khong the lap
            ke hoach an toan, bao loi thay vi tu gia dinh.
    """
    if rated_power_kw <= 0:
        raise ValueError("Cong suat dat phai lon hon 0 kW")
    if not 1 <= weekday <= 7:
        raise ValueError("weekday phai nam trong 1..7 theo ISO (1 = thu Hai)")
    if pre_cool_target_c >= base_temp_c:
        raise ValueError(
            f"Nhiet do lam lanh sau ({pre_cool_target_c}°C) phai thap hon nhiet do van hanh "
            f"({base_temp_c}°C), neu khong thi khong co nhiet nao duoc tich truoc gio cao diem"
        )

    bands = billing.active_bands(session, at=utctoday())
    if not bands:
        raise PeakShavingConfigError(
            "Chua co bieu gia EVN nao trong bang tariff_bands. Can seed bieu gia truoc khi lap "
            "ke hoach cat dinh: don gia va khung gio cao diem la du lieu nghiep vu, khong duoc "
            "tu dat trong ma nguon."
        )

    haccp_limit_c = fleet_haccp_limit_c(session)
    if haccp_limit_c is None:
        raise PeakShavingConfigError(
            "Khong thiet bi lanh dang hoat dong nao khai haccp_limit_c. Khong co nguong thi khong "
            "the bao dam cat dinh ma khong lam hong hang, nen he thong tu choi thay vi mac dinh -18 C."
        )
    if base_temp_c > haccp_limit_c:
        raise PeakShavingConfigError(
            f"Nhiet do van hanh yeu cau ({base_temp_c}°C) da vuot nguong HACCP chat nhat cua doi "
            f"xe ({haccp_limit_c}°C)."
        )

    safe_ceiling_c = haccp_limit_c - HACCP_SAFETY_MARGIN_C
    segments = weekday_segments(bands, weekday)
    if not segments:
        raise PeakShavingConfigError(
            f"Bieu gia hien hanh khong co khung gio nao cho ngay ISO {weekday}"
        )

    schedule = build_peak_shaving_schedule(segments, base_temp_c, pre_cool_target_c, safe_ceiling_c)

    peak_phases = [p for p in schedule if p["phase"].startswith("PEAK_SHAVING")]
    pre_cool_phases = [p for p in schedule if p["phase"].startswith("PRE_COOL")]
    peak_hours = sum(p["duration_hours"] for p in peak_phases)
    pre_cool_hours = sum(p["duration_hours"] for p in pre_cool_phases)
    peak_price = max((p["rate_vnd_per_kwh"] for p in peak_phases), default=None)
    pre_cool_price = max((p["rate_vnd_per_kwh"] for p in pre_cool_phases), default=None)

    if peak_hours > 0 and peak_price is not None:
        baseline_peak_kwh = peak_hours * rated_power_kw * (BASELINE_PEAK_LOAD_PCT / 100.0)
        baseline_peak_cost = baseline_peak_kwh * peak_price
        shaved_peak_kwh = peak_hours * rated_power_kw * (SHAVED_PEAK_LOAD_PCT / 100.0)
        shaved_peak_cost = shaved_peak_kwh * peak_price
        pre_cool_extra_kwh = pre_cool_hours * rated_power_kw * (PRE_COOL_EXTRA_LOAD_PCT / 100.0)
        pre_cool_extra_cost = pre_cool_extra_kwh * (pre_cool_price or 0)

        daily_saving_vnd = baseline_peak_cost - (shaved_peak_cost + pre_cool_extra_cost)
        saving_ratio_pct = (
            (daily_saving_vnd / baseline_peak_cost) * 100.0 if baseline_peak_cost > 0 else 0.0
        )
        status = "active"
        message = None
    else:
        # Ngay khong co gio cao diem (vd chu nhat theo bieu gia EVN) thi khong co gi de cat.
        # Tra ve 0 dong va noi ro ly do, hon la van tinh ra mot khoan "tiet kiem" khong co that.
        baseline_peak_kwh = baseline_peak_cost = 0.0
        shaved_peak_kwh = shaved_peak_cost = 0.0
        pre_cool_extra_kwh = pre_cool_extra_cost = 0.0
        daily_saving_vnd = 0.0
        saving_ratio_pct = 0.0
        status = "no_peak_hours"
        message = (
            f"Ngay ISO {weekday} khong co khung gio cao diem nao theo bieu gia hien hanh, "
            f"nen khong co gi de cat dinh."
        )

    return {
        "status": status,
        "message": message,
        "weekday_iso": weekday,
        "rated_power_kw": rated_power_kw,
        "base_temp_c": base_temp_c,
        "pre_cool_target_c": pre_cool_target_c,
        "haccp_limit_c": haccp_limit_c,
        "safe_operating_ceiling_c": round(safe_ceiling_c, 2),
        "haccp_safety_margin_c": HACCP_SAFETY_MARGIN_C,
        "tariff_effective_from": max(b.effective_from for b in bands).isoformat(),
        "peak_hours_per_day": round(peak_hours, 3),
        "pre_cool_hours_per_day": round(pre_cool_hours, 3),
        "peak_rate_vnd_per_kwh": peak_price,
        "baseline_peak_kwh": round(baseline_peak_kwh, 2),
        "baseline_peak_cost_vnd": round(baseline_peak_cost, 0),
        "shaved_peak_kwh": round(shaved_peak_kwh, 2),
        "shaved_peak_cost_vnd": round(shaved_peak_cost, 0),
        "pre_cool_extra_kwh": round(pre_cool_extra_kwh, 2),
        "pre_cool_extra_cost_vnd": round(pre_cool_extra_cost, 0),
        "daily_saving_vnd": round(daily_saving_vnd, 0),
        "monthly_saving_vnd": round(daily_saving_vnd * 30.0, 0),
        "peak_cost_reduction_pct": round(saving_ratio_pct, 1),
        "assumptions": {
            "baseline_peak_load_pct": BASELINE_PEAK_LOAD_PCT,
            "shaved_peak_load_pct": SHAVED_PEAK_LOAD_PCT,
            "pre_cool_extra_load_pct": PRE_COOL_EXTRA_LOAD_PCT,
            "maintain_load_pct": MAINTAIN_LOAD_PCT,
            "pre_cool_minutes": PRE_COOL_MINUTES,
            "note": (
                "He so tai (%) la phuong an van hanh do ky su chon, khong phai so lieu do. "
                "Don gia va khung gio lay tu bang tariff_bands dang hieu luc."
            ),
        },
        "schedule": schedule,
        "timestamp": utcnow().isoformat(),
    }


def _most_recent_value(
    samples: List[TelemetrySample], field: str
) -> Tuple[Optional[float], Optional[datetime]]:
    """Gia tri khac None gan nhat cua `field`, kem thoi diem do.

    `samples` da sap moi -> cu. Dau cham 0.0 la mot phep do hop le nen phai dung `is None`:
    `latest.vibration_mm_s or 1.2` vua mat con so 0 that vua ve ra mot cai may dang khoe.
    """
    for sample in samples:
        value = getattr(sample, field)
        if value is not None:
            return float(value), sample.ts
    return None, None


def diagnose_predictive_maintenance(
    session: Session,
    equipment_id: Optional[int] = None,
    sample_limit: int = TREND_SAMPLE_LIMIT,
) -> List[Dict[str, Any]]:
    """Chan doan rung ISO 10816-3 va xu huong suy giam COP cho tung thiet bi."""
    query = select(Equipment).where(Equipment.is_active.is_(True))
    if equipment_id is not None:
        query = query.where(Equipment.id == equipment_id)
    equipment_list = list(session.scalars(query.order_by(Equipment.code.asc())))

    diagnostics: List[Dict[str, Any]] = []
    for eq in equipment_list:
        samples = list(
            session.scalars(
                select(TelemetrySample)
                .where(TelemetrySample.equipment_id == eq.id)
                .order_by(desc(TelemetrySample.ts))
                .limit(sample_limit)
            )
        )

        if not samples:
            diagnostics.append({
                "equipment_id": eq.id,
                "equipment_code": eq.code,
                "equipment_name": eq.name,
                "kind": eq.kind,
                "status": "NO_DATA",
                "message": "Chưa có dữ liệu telemetry đo lường",
            })
            continue

        latest = samples[0]

        # 1. Danh gia ISO 10816-3
        vibration, vibration_ts = _most_recent_value(samples, "vibration_mm_s")
        if vibration is None:
            vibe_zone = None
            vibe_health = "NO_VIBRATION_DATA"
            vibe_recommendation = (
                "Chưa có số liệu rung động nào nên không thể đánh giá theo ISO 10816-3. "
                "Cần gắn cảm biến rung hoặc đo bằng máy cầm tay"
            )
        elif vibration < ISO_ZONE_A_MAX:
            vibe_zone = "ZONE_A"
            vibe_health = "EXCELLENT"
            vibe_recommendation = "Cơ khí hoàn hảo, không cần can thiệp"
        elif vibration < ISO_ZONE_B_MAX:
            vibe_zone = "ZONE_B"
            vibe_health = "GOOD"
            vibe_recommendation = "Độ rung nằm trong giới hạn cho phép dài hạn"
        elif vibration < ISO_ZONE_C_MAX:
            vibe_zone = "ZONE_C"
            vibe_health = "WARNING"
            vibe_recommendation = "Độ rung bất thường. Khuyến nghị kiểm tra vòng bi và độ đồng tâm trục trong vòng 30 ngày"
        else:
            vibe_zone = "ZONE_D"
            vibe_health = "CRITICAL"
            vibe_recommendation = "Độ rung nguy hiểm! Cần dừng máy kiểm tra khẩn cấp để tránh phá hủy bạc đạn trục vít"

        # 2. Do doc suy giam COP tinh theo gio that cua dau thoi gian
        cop, cop_ts = _most_recent_value(samples, "cop")
        cop_points = sorted(
            ((s.ts, float(s.cop)) for s in samples if s.cop is not None and s.ts is not None),
            key=lambda point: point[0],
        )
        cop_slope_per_hour: Optional[float] = None
        if eq.is_refrigeration and len(cop_points) >= MIN_SAMPLES_FOR_TREND:
            origin = cop_points[0][0]
            hours = [(ts - origin).total_seconds() / 3600.0 for ts, _ in cop_points]
            if hours[-1] > 0:
                cop_slope_per_hour = _linear_slope(hours, [value for _, value in cop_points])

        leak_detected = False
        leak_severity = "NONE"
        rul_days: Optional[float] = None
        rul_basis = "NOT_MODELLED"

        # Lo hoi danh gia bang hieu suat eta, khong co COP: khong duoc ap nguon ro ri moi chat.
        if eq.is_refrigeration and cop is not None:
            degrading = cop < COP_LEAK_ABSOLUTE or (
                cop_slope_per_hour is not None
                and cop_slope_per_hour * 24.0 < COP_LEAK_SLOPE_PER_DAY
            )
            if degrading:
                leak_detected = True
                leak_severity = "CRITICAL" if cop < COP_CRITICAL_ABSOLUTE else "WARNING"
                if cop_slope_per_hour is not None and cop_slope_per_hour < 0:
                    hours_to_failure = (cop - COP_FAILURE_THRESHOLD) / abs(cop_slope_per_hour)
                    rul_days = round(max(0.0, hours_to_failure) / 24.0, 1)
                    rul_basis = "COP_TREND"

        # 3. Tong hop de xuat bao tri
        actions: List[str] = []
        if vibe_health in ("WARNING", "CRITICAL", "NO_VIBRATION_DATA"):
            actions.append(vibe_recommendation)
        if leak_detected:
            # Ten moi chat lay tu ho so thiet bi: CHILLER_01 chay R134a ma bao "ro ri R404A"
            # la bao cao sai va dua tho sua chua di tim dung loai gas.
            refrigerant = eq.refrigerant or "môi chất lạnh"
            slope_text = (
                f"độ dốc {cop_slope_per_hour:.4f}/giờ"
                if cop_slope_per_hour is not None
                else "COP thấp bất thường"
            )
            actions.append(
                f"Phát hiện suy giảm hệ số COP ({slope_text}). "
                f"Khả năng cao rò rỉ {refrigerant} - Cần nạp gas và rà soát van tiết lưu"
            )
        if rul_days is not None and rul_days <= 1.0:
            actions.append(
                f"Theo xu hướng hiện tại, COP sẽ chạm ngưỡng hỏng {COP_FAILURE_THRESHOLD} "
                "trong vòng 24 giờ - cần lên phương án dự phòng ngay"
            )

        if not actions:
            actions.append("Hệ thống hoạt động ổn định và hiệu quả")

        diagnostics.append({
            "equipment_id": eq.id,
            "equipment_code": eq.code,
            "equipment_name": eq.name,
            "kind": eq.kind,
            "status": "DIAGNOSED",
            "refrigerant": eq.refrigerant,
            "vibration_mm_s": round(vibration, 2) if vibration is not None else None,
            "vibration_measured_at": vibration_ts.isoformat() if vibration_ts else None,
            "iso_zone": vibe_zone,
            "vibration_health": vibe_health,
            "cop_current": round(cop, 2) if cop is not None else None,
            "cop_measured_at": cop_ts.isoformat() if cop_ts else None,
            #: Thong so thiet ke chi de so sanh, KHONG duoc thay the cho COP do duoc.
            "design_cop": eq.design_cop,
            "cop_samples_used": len(cop_points),
            "cop_slope": round(cop_slope_per_hour, 4) if cop_slope_per_hour is not None else None,
            "cop_slope_unit": "COP per hour",
            "cop_slope_per_day": (
                round(cop_slope_per_hour * 24.0, 4) if cop_slope_per_hour is not None else None
            ),
            "refrigerant_leak_suspected": leak_detected,
            "leak_severity": leak_severity,
            "estimated_rul_days": rul_days,
            "rul_basis": rul_basis,
            "recommended_actions": actions,
            "last_measured_at": latest.ts.isoformat() if latest.ts else None,
        })

    return diagnostics
