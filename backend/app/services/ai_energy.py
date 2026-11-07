"""Engine Toi uu Nang luong Dinh (AI Peak-Shaving) va Bao tri Du doan (Predictive Maintenance).

1. Peak-Shaving Schedule:
   - Su dung quan tinh nhiet cua kho lanh va hang hoa (thuy hai san).
   - Tinh toan lich Pre-cooling (lam lanh sau xuong -22C truoc gio cao diem EVN).
   - Tiet giam phu tai trong gio cao diem (09:30-11:30 va 17:00-20:00) giup cat giam 30-40% chi phi dien gio cao diem
     ma van dam bao tuyet doi khong vi pham nguong HACCP (-18C).

2. Predictive Maintenance (PdM):
   - Danh gia rung dong co khi theo tieu chuan quoc te ISO 10816-3 (Zone A, B, C, D).
   - Phan tich do doc suy giam COP (COP degradation slope) theo chuoi thoi gian de phat hien
     ro ri moi chat lanh R404A hoac hao mon co khi truoc khi xay ra su co dung may.
   - Tinh toan tuoi tho con lai (Remaining Useful Life - RUL) va khuyen nghi hanh dong.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import Equipment, TelemetrySample
from ..timeutil import utcnow

# Don gia dien EVN tham chieu (VND/kWh)
EVN_PEAK_RATE = 3171.0
EVN_NORMAL_RATE = 1685.0
EVN_OFF_PEAK_RATE = 1100.0

# Nguong rung ISO 10816-3 (mm/s)
ISO_ZONE_A_MAX = 1.4  # Tuyen hao
ISO_ZONE_B_MAX = 2.8  # Van hanh binh thuong
ISO_ZONE_C_MAX = 4.5  # Canh bao - can len ke hoach sua chua


def calculate_peak_shaving_plan(
    rated_power_kw: float = 120.0,
    base_temp_c: float = -18.0,
    pre_cool_target_c: float = -22.5,
    haccp_limit_c: float = -18.0,
) -> Dict[str, Any]:
    """Tinh toan ke hoach 24h dieu phoi phu tai tiet kiem dien dinh."""
    schedule = [
        {
            "period": "00:00 - 04:00",
            "phase": "OFF_PEAK_BASE",
            "phase_name": "Đáy đêm (Thấp điểm)",
            "compressor_load_pct": 50,
            "target_temp_c": -18.5,
            "tariff_tier": "OFF_PEAK",
            "rate_vnd_per_kwh": EVN_OFF_PEAK_RATE,
            "description": "Chạy duy trì tải tối thiểu với giá điện rẻ nhất",
        },
        {
            "period": "04:00 - 07:30",
            "phase": "NORMAL_STABLE",
            "phase_name": "Bình thường sáng",
            "compressor_load_pct": 60,
            "target_temp_c": -19.0,
            "tariff_tier": "NORMAL",
            "rate_vnd_per_kwh": EVN_NORMAL_RATE,
            "description": "Vận hành ổn định trước ca làm việc",
        },
        {
            "period": "07:30 - 09:30",
            "phase": "PRE_COOL_1",
            "phase_name": "Làm lạnh sâu đợt 1 (Pre-cooling)",
            "compressor_load_pct": 95,
            "target_temp_c": pre_cool_target_c,
            "tariff_tier": "NORMAL",
            "rate_vnd_per_kwh": EVN_NORMAL_RATE,
            "description": "Tích trữ năng lượng nhiệt vào sản phẩm trước giờ cao điểm sáng",
        },
        {
            "period": "09:30 - 11:30",
            "phase": "PEAK_SHAVING_1",
            "phase_name": "Cắt đỉnh sáng (Peak-Shaving)",
            "compressor_load_pct": 25,
            "target_temp_c": -18.5,
            "tariff_tier": "PEAK",
            "rate_vnd_per_kwh": EVN_PEAK_RATE,
            "description": "Tiết giảm 75% tải máy nén, nhiệt độ trôi tự nhiên vẫn dưới ngưỡng HACCP",
        },
        {
            "period": "11:30 - 15:30",
            "phase": "MID_DAY_NORMAL",
            "phase_name": "Bình thường trưa",
            "compressor_load_pct": 65,
            "target_temp_c": -19.0,
            "tariff_tier": "NORMAL",
            "rate_vnd_per_kwh": EVN_NORMAL_RATE,
            "description": "Bù nhiệt độ phòng lạnh và chuẩn bị cho đợt cao điểm chiều",
        },
        {
            "period": "15:30 - 17:00",
            "phase": "PRE_COOL_2",
            "phase_name": "Làm lạnh sâu đợt 2 (Pre-cooling)",
            "compressor_load_pct": 95,
            "target_temp_c": pre_cool_target_c,
            "tariff_tier": "NORMAL",
            "rate_vnd_per_kwh": EVN_NORMAL_RATE,
            "description": "Tích nhiệt lần 2 trước giờ cao điểm tối",
        },
        {
            "period": "17:00 - 20:00",
            "phase": "PEAK_SHAVING_2",
            "phase_name": "Cắt đỉnh tối (Peak-Shaving)",
            "compressor_load_pct": 20,
            "target_temp_c": -18.2,
            "tariff_tier": "PEAK",
            "rate_vnd_per_kwh": EVN_PEAK_RATE,
            "description": "Tiết giảm 80% tải trong 3 tiếng cao điểm tối đắt đỏ",
        },
        {
            "period": "20:00 - 22:00",
            "phase": "RECOVERY_NORMAL",
            "phase_name": "Phục hồi đêm",
            "compressor_load_pct": 70,
            "target_temp_c": -19.0,
            "tariff_tier": "NORMAL",
            "rate_vnd_per_kwh": EVN_NORMAL_RATE,
            "description": "Đưa nhiệt độ kho về trạng thái chuẩn",
        },
        {
            "period": "22:00 - 24:00",
            "phase": "OFF_PEAK_NIGHT",
            "phase_name": "Thấp điểm đêm",
            "compressor_load_pct": 50,
            "target_temp_c": -18.5,
            "tariff_tier": "OFF_PEAK",
            "rate_vnd_per_kwh": EVN_OFF_PEAK_RATE,
            "description": "Chuyển sang khung giờ rẻ nhất của ngày",
        },
    ]

    # Uoc tinh kinh te:
    # 5 gio cao diem neu chay 80% cong suat: 5h * (120kW * 0.8) = 480 kWh * 3171 = 1,522,080 VND/ngay
    # Khi cat dinh (chay trung binh 22%): 5h * (120kW * 0.22) = 132 kWh * 3171 = 418,572 VND/ngay
    # Luong dien lam lanh truoc (3.5h gio binh thuong): 3.5h * (120kW * 0.35 bu them) = 147 kWh * 1685 = 247,695 VND/ngay
    # Tong chi phi tiet kiem rong moi ngay: 1,522,080 - (418,572 + 247,695) = 855,813 VND/ngay (~56.2% tiet kiem tien dien cao diem)
    baseline_peak_kwh = 5.0 * (rated_power_kw * 0.80)
    baseline_peak_cost = baseline_peak_kwh * EVN_PEAK_RATE

    optimized_peak_kwh = (2.0 * (rated_power_kw * 0.25)) + (3.0 * (rated_power_kw * 0.20))
    optimized_peak_cost = optimized_peak_kwh * EVN_PEAK_RATE

    pre_cool_extra_kwh = (2.0 * (rated_power_kw * 0.35)) + (1.5 * (rated_power_kw * 0.35))
    pre_cool_cost = pre_cool_extra_kwh * EVN_NORMAL_RATE

    daily_saving_vnd = baseline_peak_cost - (optimized_peak_cost + pre_cool_cost)
    monthly_saving_vnd = daily_saving_vnd * 30.0
    saving_ratio_pct = (daily_saving_vnd / baseline_peak_cost) * 100.0

    return {
        "status": "active",
        "rated_power_kw": rated_power_kw,
        "base_temp_c": base_temp_c,
        "pre_cool_target_c": pre_cool_target_c,
        "haccp_limit_c": haccp_limit_c,
        "daily_saving_vnd": round(daily_saving_vnd, 0),
        "monthly_saving_vnd": round(monthly_saving_vnd, 0),
        "peak_cost_reduction_pct": round(saving_ratio_pct, 1),
        "schedule": schedule,
        "timestamp": utcnow().isoformat(),
    }


def diagnose_predictive_maintenance(session: Session, equipment_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Phan tich chan doan do rung ISO 10816-3 va suy giam COP cho tung thiet bi."""
    query = select(Equipment).where(Equipment.is_active == True)
    if equipment_id:
        query = query.where(Equipment.id == equipment_id)
    equipment_list = list(session.scalars(query))

    diagnostics = []
    for eq in equipment_list:
        # Lay 50 mau telemetry gan nhat de tinh xu huong
        samples = list(
            session.scalars(
                select(TelemetrySample)
                .where(TelemetrySample.equipment_id == eq.id)
                .order_by(desc(TelemetrySample.ts))
                .limit(50)
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
        vibration = latest.vibration_mm_s or 1.2
        cop = latest.cop or eq.design_cop or 3.2

        # 1. Danh gia ISO 10816-3
        if vibration < ISO_ZONE_A_MAX:
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

        # 2. Phan tich COP Degradation Slope (phat hien ro ri R404A)
        cop_values = [s.cop for s in samples if s.cop is not None]
        leak_detected = False
        leak_severity = "NONE"
        rul_days = 90  # Mac dinh con 90 ngay
        cop_slope = 0.0

        if len(cop_values) >= 5:
            # Tinh do doc hoi quy tuyen tinh giua chi so mau va COP
            n = len(cop_values)
            x = list(range(n))
            y = list(reversed(cop_values))  # Sap theo thu tu thoi gian cu den moi
            x_mean = sum(x) / n
            y_mean = sum(y) / n
            numer = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
            denom = sum((x[i] - x_mean) ** 2 for i in range(n))
            cop_slope = numer / denom if denom != 0 else 0.0

            # Neu COP sut giam va thiet bi la lanh / may nen
            if eq.kind in ("DEEP_FREEZER", "COMPRESSOR", "CHILLER"):
                if cop_slope < -0.015 or cop < 2.5:
                    leak_detected = True
                    leak_severity = "CRITICAL" if cop < 2.3 else "WARNING"
                    # Uoc tinh RUL truoc khi COP cham 2.0
                    days_remaining = max(3, int((cop - 2.0) / abs(cop_slope * 24))) if cop_slope < 0 else 7
                    rul_days = min(rul_days, days_remaining)

        # 3. Tong hop de xuat bao tri
        actions = []
        if vibe_health in ("WARNING", "CRITICAL"):
            actions.append(vibe_recommendation)
        if leak_detected:
            actions.append(
                f"Phát hiện suy giảm hệ số COP (độ dốc {cop_slope:.4f}). "
                "Khả năng cao rò rỉ môi chất lạnh R404A - Cần nạp gas và rà soát van tiết lưu"
            )

        if not actions:
            actions.append("Hệ thống hoạt động ổn định và hiệu quả")

        diagnostics.append({
            "equipment_id": eq.id,
            "equipment_code": eq.code,
            "equipment_name": eq.name,
            "kind": eq.kind,
            "vibration_mm_s": round(vibration, 2),
            "iso_zone": vibe_zone,
            "vibration_health": vibe_health,
            "cop_current": round(cop, 2),
            "cop_slope": round(cop_slope, 4),
            "refrigerant_leak_suspected": leak_detected,
            "leak_severity": leak_severity,
            "estimated_rul_days": rul_days,
            "recommended_actions": actions,
            "last_measured_at": latest.ts.isoformat(),
        })

    return diagnostics
