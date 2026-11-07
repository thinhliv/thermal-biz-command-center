"""Du lieu khoi tao (seed) cho dev/demo.

Nguyen tac:
- IDEMPOTENT: chi seed khi bang rong. Chay lai khong tao du lieu trung.
- COHERENT: COP = Q_o / N_e duoc TINH ra, khong bịa. Canh bao do `evaluate_sample`
  sinh ra tu rule, khong hardcode chuoi text nhu ban mock cu.
- DETERMINISTIC: dung `random.Random(SEED)` de moi lan demo ra cung mot kich ban.

Gia dien EVN o day la gia minh hoa theo bieu gia kinh doanh cap dien ap trung binh.
Khi EVN ra quyet dinh moi, sua `EVN_PRICES` va them bo band voi `effective_from` moi -
`active_bands()` tu lay bo gan nhat, khong can xoa du lieu cu.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    Alert,
    AlarmRule,
    BilledInvoice,
    Comparator,
    Customer,
    Equipment,
    EquipmentKind,
    EquipmentStatus,
    MeterReading,
    Metric,
    MonthlyTarget,
    OrderStatus,
    Receivable,
    ReceivableStatus,
    Role,
    ServiceOrder,
    Severity,
    TariffBand,
    TariffBandCode,
    TelemetrySample,
    User,
)
from .security import hash_password
from .services import billing, thermal
from .timeutil import month_bounds, utcnow, utctoday

RANDOM_SEED = 20260107

#: VND/kWh - bieu gia kinh doanh, cap dien ap trung binh (gia minh hoa)
EVN_PRICES = {
    TariffBandCode.PEAK: 4586,
    TariffBandCode.NORMAL: 2824,
    TariffBandCode.OFF_PEAK: 1808,
}

BAND_NAMES = {
    TariffBandCode.PEAK: "Giờ cao điểm",
    TariffBandCode.NORMAL: "Giờ bình thường",
    TariffBandCode.OFF_PEAK: "Giờ thấp điểm",
}

#: ISO weekday: thu 2..thu 7. Chu nhat khong co gio cao diem theo quy dinh EVN.
WEEKDAY_MON_SAT = "1,2,3,4,5,6"
WEEKDAY_SUN = "7"

# (code, start_minute, end_minute, days) - phu kin 24h de `band_minutes` tinh dung
EVN_SCHEDULE: list[tuple[TariffBandCode, int, int, str]] = [
    (TariffBandCode.OFF_PEAK, 0, 240, "*"),        # 00:00-04:00
    (TariffBandCode.NORMAL, 240, 570, WEEKDAY_MON_SAT),   # 04:00-09:30
    (TariffBandCode.PEAK, 570, 690, WEEKDAY_MON_SAT),     # 09:30-11:30
    (TariffBandCode.NORMAL, 690, 1020, WEEKDAY_MON_SAT),  # 11:30-17:00
    (TariffBandCode.PEAK, 1020, 1200, WEEKDAY_MON_SAT),   # 17:00-20:00
    (TariffBandCode.NORMAL, 1200, 1320, WEEKDAY_MON_SAT), # 20:00-22:00
    (TariffBandCode.OFF_PEAK, 1320, 1440, "*"),    # 22:00-24:00
    (TariffBandCode.NORMAL, 240, 1320, WEEKDAY_SUN),      # chu nhat: 04:00-22:00
]


def _effective_from() -> date:
    today = utctoday()
    target = date(2026, 1, 1)
    return target if target <= today else today


# --------------------------------------------------------------------------- #
# Nguoi dung
# --------------------------------------------------------------------------- #
DEMO_USERS = [
    ("bgd", Role.BGD, "Nguyễn Văn Hùng", "Tổng Giám đốc"),
    ("vanhanh", Role.VANHANH, "Trần Thị Mai", "Trưởng ca Vận hành"),
    ("ketoan", Role.KETOAN, "Lê Quốc Bảo", "Kế toán trưởng"),
]


def seed_users(session: Session, password: str) -> list[User]:
    created: list[User] = []
    for username, role, full_name, note in DEMO_USERS:
        if session.scalars(select(User).where(User.username == username)).first():
            continue
        user = User(
            username=username,
            password_hash=hash_password(password),
            full_name=f"{full_name} ({note})",
            role=role.value,
            is_active=True,
        )
        session.add(user)
        created.append(user)
    session.flush()
    return created


# --------------------------------------------------------------------------- #
# Bieu gia EVN
# --------------------------------------------------------------------------- #
def seed_tariff_bands(session: Session) -> int:
    if session.scalars(select(TariffBand).limit(1)).first():
        return 0
    effective = _effective_from()
    for code, start, end, days in EVN_SCHEDULE:
        session.add(
            TariffBand(
                code=code.value,
                name_vn=BAND_NAMES[code],
                start_minute=start,
                end_minute=end,
                days=days,
                price_vnd_per_kwh=EVN_PRICES[code],
                effective_from=effective,
                is_active=True,
            )
        )
    session.flush()
    return len(EVN_SCHEDULE)


# --------------------------------------------------------------------------- #
# Thiet bi
# --------------------------------------------------------------------------- #
# (code, name, kind, location, refrigerant, rated_kw, setpoint, haccp, design_cop, design_eta, tenant, meter)
EQUIPMENT_SPEC: list[dict] = [
    {
        "code": "KHO_DONG_01",
        "name": "Kho Đông Sâu Hải Sản 01 (-25°C)",
        "kind": EquipmentKind.DEEP_FREEZER,
        "location": "Nhà A - Khu chế biến hải sản",
        "refrigerant": "R404A",
        "rated_power_kw": 45.0,
        "setpoint_c": -25.0,
        "haccp_limit_c": -18.0,
        "design_cop": 3.8,
    },
    {
        "code": "KHO_DONG_02",
        "name": "Kho Đông Thuê - Công ty An Phát (-22°C)",
        "kind": EquipmentKind.DEEP_FREEZER,
        "location": "Nhà B - Khu cho thuê",
        "refrigerant": "R404A",
        "rated_power_kw": 38.0,
        "setpoint_c": -22.0,
        "haccp_limit_c": -18.0,
        "design_cop": 3.6,
        "tenant_code": "THUE-ANPHAT",
        "meter_entity_id": "sensor.anphat_kho_dong_energy",
    },
    {
        "code": "KHO_MAT_01",
        "name": "Kho Mát Nông Sản & Trái Cây (+2°C)",
        "kind": EquipmentKind.COLD_ROOM,
        "location": "Nhà C - Khu nông sản",
        "refrigerant": "R404A",
        "rated_power_kw": 18.0,
        "setpoint_c": 2.0,
        "haccp_limit_c": 5.0,
        "design_cop": 4.2,
        "tenant_code": "THUE-HOANGGIA",
        "meter_entity_id": "sensor.hoanggia_kho_mat_energy",
    },
    {
        "code": "CAP_DONG_01",
        "name": "Hầm Cấp Đông Gió Nhanh 01 (-35°C)",
        "kind": EquipmentKind.BLAST_FREEZER,
        "location": "Nhà A - Dây chuyền IQF",
        "refrigerant": "R404A",
        "rated_power_kw": 92.0,
        "setpoint_c": -35.0,
        "haccp_limit_c": -18.0,
        "design_cop": 3.1,
    },
    {
        "code": "CHILLER_01",
        "name": "Trạm Chiller Trung Tâm (+7°C)",
        "kind": EquipmentKind.CHILLER,
        "location": "Sân thượng - Nhà văn phòng",
        "refrigerant": "R134a",
        "rated_power_kw": 75.0,
        "setpoint_c": 7.0,
        "design_cop": 4.8,
    },
    {
        "code": "MAY_NEN_01",
        "name": "Cụm Máy Nén Trục Vít Trung Tâm",
        "kind": EquipmentKind.COMPRESSOR,
        "location": "Phòng máy - Nhà A",
        "refrigerant": "R404A",
        "rated_power_kw": 120.0,
        # Nhiet do bay hoi dich (-30C) cap cho cac kho -22/-25C; R404A o muc nay ~1.3-2.1 bar
        "setpoint_c": -30.0,
        "design_cop": 3.4,
    },
    {
        "code": "LO_HOI_01",
        "name": "Lò Hơi Đốt Tầng Sôi Sinh Khối 01",
        "kind": EquipmentKind.BOILER,
        "location": "Nhà năng lượng",
        "rated_power_kw": 48.0,
        "design_efficiency_pct": 85.0,
    },
    {
        "code": "LO_HOI_02",
        "name": "Lò Hơi Đốt Than 02 (Hơi bão hòa)",
        "kind": EquipmentKind.BOILER,
        "location": "Nhà năng lượng",
        "rated_power_kw": 52.0,
        "design_efficiency_pct": 82.0,
    },
]


def seed_equipment(session: Session) -> list[Equipment]:
    existing = {e.code for e in session.scalars(select(Equipment))}
    created: list[Equipment] = []
    for spec in EQUIPMENT_SPEC:
        if spec["code"] in existing:
            continue
        item = Equipment(
            commissioned_at=date(2021, 3, 15),
            is_active=True,
            **spec,
        )
        session.add(item)
        created.append(item)
    session.flush()
    return list(session.scalars(select(Equipment).order_by(Equipment.code)))


# --------------------------------------------------------------------------- #
# Nguong canh bao (khai bao, khong hardcode trong code xu ly)
# --------------------------------------------------------------------------- #
RULE_SPEC: list[dict] = [
    {
        "applies_to_kind": EquipmentKind.DEEP_FREEZER.value,
        "metric": Metric.TEMPERATURE_C,
        "comparator": Comparator.GT,
        "threshold": -18.0,
        "duration_minutes": 0,
        "severity": Severity.CRITICAL,
        "is_haccp": True,
        "message_template": (
            "HACCP - {equipment}: nhiệt độ {value:.1f}°C vượt giới hạn an toàn "
            "{threshold:.1f}°C. Hải sản có nguy cơ mất chất lượng, kiểm tra ngay."
        ),
    },
    {
        "applies_to_kind": EquipmentKind.BLAST_FREEZER.value,
        "metric": Metric.TEMPERATURE_C,
        "comparator": Comparator.GT,
        "threshold": -18.0,
        "duration_minutes": 0,
        "severity": Severity.CRITICAL,
        "is_haccp": True,
        "message_template": (
            "HACCP - {equipment}: nhiệt độ {value:.1f}°C vượt giới hạn {threshold:.1f}°C."
        ),
    },
    {
        "applies_to_kind": None,
        "metric": Metric.COP,
        "comparator": Comparator.LT,
        "threshold": 2.8,
        "duration_minutes": 30,
        "severity": Severity.MAJOR,
        "message_template": (
            "{equipment}: COP {value:.2f} thấp hơn {threshold:.2f} kéo dài >30 phút. "
            "Nghi thiếu gas lạnh hoặc dàn nóng bẩn - kiểm tra áp suất bay hơi và vệ dàn."
        ),
    },
    {
        "applies_to_kind": None,
        "metric": Metric.VIBRATION_MM_S,
        "comparator": Comparator.GT,
        "threshold": thermal.VIBRATION_ISO10816_LIMIT_MM_S,
        "duration_minutes": 15,
        "severity": Severity.WARNING,
        "message_template": (
            "{equipment}: rung {value:.2f} mm/s vượt ranh giới vùng C/D ISO 10816-3 "
            "({threshold:.1f} mm/s). Lên lịch căn trục / kiểm tra bạc đạn."
        ),
    },
    {
        "applies_to_kind": EquipmentKind.BOILER.value,
        "metric": Metric.EFFICIENCY_PCT,
        "comparator": Comparator.LT,
        "threshold": 75.0,
        "duration_minutes": 30,
        "severity": Severity.WARNING,
        "message_template": (
            "{equipment}: hiệu suất đốt {value:.1f}% thấp hơn {threshold:.1f}%. "
            "Kiểm tra hệ số gió thừa và muội than trong ống khói."
        ),
    },
    {
        "applies_to_kind": EquipmentKind.CHILLER.value,
        "metric": Metric.PRESSURE_BAR,
        "comparator": Comparator.GT,
        "threshold": 9.5,
        "duration_minutes": 10,
        "severity": Severity.MAJOR,
        "message_template": (
            "{equipment}: áp suất ngưng tụ {value:.2f} bar vượt {threshold:.1f} bar. "
            "Kiểm tra tháp giải nhiệt và lưu lượng nước làm mát."
        ),
    },
]


def seed_alarm_rules(session: Session) -> int:
    if session.scalars(select(AlarmRule).limit(1)).first():
        return 0
    for spec in RULE_SPEC:
        session.add(AlarmRule(enabled=True, **spec))
    session.flush()
    return len(RULE_SPEC)


# --------------------------------------------------------------------------- #
# Telemetry - 30 gio, buoc 15 phut
# --------------------------------------------------------------------------- #
SAMPLE_STEP_MIN = 15
SAMPLE_HOURS = 30


def _profile_for(code: str, spec: dict) -> dict:
    """Kich ban van hanh rieng cho tung thiet bi de sinh ra canh bao THAT."""
    kind = spec["kind"]
    is_boiler = kind == EquipmentKind.BOILER
    return {
        "base_power": spec["rated_power_kw"] * (0.55 if is_boiler else 0.72),
        "is_boiler": is_boiler,
        # COP suy giam dan -> cham nguong COP < 2.8
        "cop_degrading": code == "CAP_DONG_01",
        # Rung tang dan -> cham ISO 10816
        "vibration_ramping": code == "MAY_NEN_01",
        # Hieu suat lo hoi sut -> cham nguong 75%
        "eta_degrading": code == "LO_HOI_02",
        # Co chu ky pha bang (defrost) lam nhiet do vut qua gioi han HACCP
        "defrosting": code == "KHO_DONG_01",
    }


def _sample_for(spec: dict, profile: dict, rng: random.Random, moment: datetime, idx: int, total: int) -> dict:
    progress = idx / max(1, total - 1)  # 0 = dau chuoi, 1 = bay gio
    hour = moment.hour + moment.minute / 60
    # Phu tai dinh vao khung 09-11h va 17-20h (dung nhu gio cao diem EVN)
    load_curve = 1.0 + 0.18 * (
        (1.0 if 9 <= hour < 12 else 0.0) + (1.0 if 17 <= hour < 20 else 0.0)
    ) - 0.22 * (1.0 if 22 <= hour or hour < 5 else 0.0)

    power_kw = round(profile["base_power"] * load_curve * rng.uniform(0.92, 1.08), 2)

    if profile["is_boiler"]:
        design_eta = spec["design_efficiency_pct"]
        eta = design_eta * rng.uniform(0.98, 1.01)
        if profile["eta_degrading"]:
            eta = design_eta - progress * (design_eta - 71.0) + rng.uniform(-0.6, 0.6)
        eta = round(min(eta, 96.0), 2)
        return {
            "ts": moment,
            "temperature_c": round(rng.uniform(172.0, 184.0), 2),
            "pressure_bar": round(rng.uniform(8.6, 9.6), 2),
            "power_kw": power_kw,
            "cooling_capacity_kw": None,
            "cop": None,                 # lo hoi KHONG co COP
            "efficiency_pct": eta,
            "vibration_mm_s": round(rng.uniform(1.4, 2.6), 2),
            "status": EquipmentStatus.RUNNING.value,
        }

    design_cop = spec["design_cop"]
    cop = design_cop * rng.uniform(0.93, 1.0)
    if profile["cop_degrading"]:
        # tu 100% thiet ke tụt xuong ~2.45 de vuot nguong canh bao
        cop = design_cop * (1.0 - progress * 0.21) + rng.uniform(-0.04, 0.04)
    cop = round(cop, 3)

    cooling_kw = round(power_kw * cop, 2)
    setpoint = spec["setpoint_c"]
    temperature_c = setpoint + rng.uniform(-0.9, 1.1)
    status = EquipmentStatus.RUNNING.value

    if profile["defrosting"] and idx % 24 in (20, 21, 22):
        temperature_c = setpoint + rng.uniform(9.0, 12.0)  # pha bang: vut len tren -18C
        status = EquipmentStatus.DEFROST.value
        cop = round(design_cop * rng.uniform(0.35, 0.5), 3)
        cooling_kw = round(power_kw * cop, 2)

    vibration = rng.uniform(1.1, 2.9)
    if profile["vibration_ramping"]:
        vibration = 1.6 + progress * 3.7 + rng.uniform(-0.2, 0.2)  # len ~5.1 mm/s
    vibration = round(vibration, 2)

    pressure = round(rng.uniform(1.3, 2.1) if setpoint < 0 else rng.uniform(3.1, 4.4), 2)
    if spec["kind"] == EquipmentKind.CHILLER:
        pressure = round(rng.uniform(8.2, 9.2), 2)

    return {
        "ts": moment,
        "temperature_c": round(temperature_c, 2),
        "pressure_bar": pressure,
        "power_kw": power_kw,
        "cooling_capacity_kw": cooling_kw,
        "cop": cop,
        "efficiency_pct": None,           # thiet bi lanh KHONG co hieu suat dot
        "vibration_mm_s": vibration,
        "status": status,
    }


def seed_telemetry(session: Session, equipment: list[Equipment], rng: random.Random) -> int:
    spec_by_code = {s["code"]: s for s in EQUIPMENT_SPEC}
    if session.scalars(select(TelemetrySample).limit(1)).first():
        return 0

    now = utcnow().replace(second=0, microsecond=0)
    start = now - timedelta(hours=SAMPLE_HOURS)
    total = SAMPLE_HOURS * 60 // SAMPLE_STEP_MIN + 1
    rows = 0

    for item in equipment:
        spec = spec_by_code.get(item.code)
        if spec is None:
            continue
        profile = _profile_for(item.code, spec)
        cumulative = rng.uniform(40_000, 120_000)

        for idx in range(total):
            moment = start + timedelta(minutes=idx * SAMPLE_STEP_MIN)
            payload = _sample_for(spec, profile, rng, moment, idx, total)
            cumulative += payload["power_kw"] * (SAMPLE_STEP_MIN / 60)
            session.add(
                TelemetrySample(
                    equipment_id=item.id,
                    energy_kwh_cumulative=round(cumulative, 3),
                    **payload,
                )
            )
            rows += 1

    session.flush()
    return rows


def seed_alerts_from_telemetry(session: Session, equipment: list[Equipment]) -> int:
    """Danh gia 6 gio gan nhat de sinh Alert THAT tu AlarmRule (khong hardcode)."""
    cutoff = utcnow() - timedelta(hours=6)
    created = 0
    for item in equipment:
        samples = list(
            session.scalars(
                select(TelemetrySample)
                .where(TelemetrySample.equipment_id == item.id, TelemetrySample.ts >= cutoff)
                .order_by(TelemetrySample.ts)
            )
        )
        for sample in samples:
            created += len(thermal.evaluate_sample(session, item, sample))
    session.commit()
    return created


def seed_alert_history(session: Session, users: list[User]) -> int:
    """Vai canh bao DA DONG/DA XAC NHAN de man hinh Canh bao co lich su, khong trong tron."""
    if session.scalars(select(Alert).where(Alert.cleared_at.is_not(None)).limit(1)).first():
        return 0
    ack_by = users[1].id if len(users) > 1 else (users[0].id if users else None)
    now = utcnow()
    history = [
        (
            Severity.MAJOR.value,
            Metric.COP.value,
            "CAP_DONG_01",
            2.61,
            2.8,
            "Hầm Cấp Đông Gió Nhanh 01: COP 2.61 thấp hơn 2.80 kéo dài >30 phút. "
            "Đã vệ dàn nóng và nạp bổ sung 12 kg R404A, COP phục hồi 3.02.",
            False,
            52,
        ),
        (
            Severity.WARNING.value,
            Metric.VIBRATION_MM_S.value,
            "MAY_NEN_01",
            4.82,
            4.5,
            "Cụm Máy Nén Trục Vít: rung 4.82 mm/s vượt ranh giới ISO 10816-3. "
            "Đã căn trục và thay bạc đạn trục vít A.",
            False,
            27,
        ),
        (
            Severity.CRITICAL.value,
            Metric.TEMPERATURE_C.value,
            "KHO_DONG_02",
            -16.4,
            -18.0,
            "HACCP - Kho Đông Thuê An Phát: nhiệt độ -16.4°C vượt giới hạn -18.0°C "
            "trong 40 phút do cửa kho mở. Đã lập biên bản và đóng cửa, nhiệt độ về -21.8°C.",
            True,
            9,
        ),
        (
            Severity.WARNING.value,
            Metric.EFFICIENCY_PCT.value,
            "LO_HOI_01",
            73.8,
            75.0,
            "Lò Hơi Sinh Khối 01: hiệu suất đốt 73.8% thấp hơn 75.0%. "
            "Đã làm sạch muội ống khói và chỉnh hệ số gió thừa từ 1.45 về 1.18.",
            False,
            3,
        ),
    ]
    for severity, metric, code, observed, threshold, message, is_haccp, hours_ago in history:
        item = session.scalars(select(Equipment).where(Equipment.code == code)).first()
        if item is None:
            continue
        raised = now - timedelta(hours=hours_ago)
        session.add(
            Alert(
                rule_id=None,
                equipment_id=item.id,
                severity=severity,
                metric=metric,
                observed_value=observed,
                threshold=threshold,
                message=message,
                is_haccp=is_haccp,
                raised_at=raised,
                cleared_at=raised + timedelta(minutes=rng_duration(hours_ago)),
                acknowledged_at=raised + timedelta(minutes=12),
                acknowledged_by_id=ack_by,
            )
        )
    session.flush()
    return len(history)


def rng_duration(hours_ago: int) -> int:
    """Thoi gian xu ly su co (phut) - ngan hon khi su co vua moi xay ra."""
    return min(180, 25 + hours_ago * 3)


# --------------------------------------------------------------------------- #
# Kinh doanh
# --------------------------------------------------------------------------- #
CUSTOMER_SPEC: list[dict] = [
    {
        "code": "KH-001",
        "name": "Công ty CP Thủy sản Biển Đông",
        "tax_id": "0301234567",
        "contact_name": "Phạm Quốc Tuấn",
        "contact_phone": "0903111222",
        "email": "ketoan@biendongseafood.vn",
        "credit_limit_vnd": 900_000_000,
        "payment_term_days": 30,
    },
    {
        "code": "KH-002",
        "name": "Tập đoàn Nông nghiệp Hoàng Gia",
        "tax_id": "0302345678",
        "contact_name": "Đỗ Thị Lan",
        "contact_phone": "0913777888",
        "email": "ap@hoanggiaagri.com",
        "credit_limit_vnd": 1_200_000_000,
        "payment_term_days": 45,
    },
    {
        "code": "KH-003",
        "name": "Chuỗi Cung Ứng Lạnh MegaCold",
        "tax_id": "0303456789",
        "contact_name": "Vũ Minh Hoàng",
        "contact_phone": "0938444555",
        "email": "ops@megacold.vn",
        "credit_limit_vnd": 600_000_000,
        "payment_term_days": 30,
    },
    {
        "code": "KH-004",
        "name": "Nhà máy Dệt May Tân Bình",
        "tax_id": "0304567890",
        "contact_name": "Hoàng Văn Sỹ",
        "contact_phone": "0902666777",
        "email": "kysu@tanbinhtex.vn",
        "credit_limit_vnd": 800_000_000,
        "payment_term_days": 15,
    },
    {
        "code": "KH-005",
        "name": "Công ty CP Chế biến Thực phẩm An Phát",
        "tax_id": "0305678901",
        "contact_name": "Ngô Thị Hạnh",
        "contact_phone": "0917333444",
        "email": "hanh.ngo@anphatfood.vn",
        "credit_limit_vnd": 400_000_000,
        "payment_term_days": 30,
    },
    {
        "code": "KH-006",
        "name": "Hợp tác xã Rau Hoa Đà Lạt",
        "tax_id": "0306789012",
        "contact_name": "Nguyễn Văn Đạt",
        "contact_phone": "0946222333",
        "email": "datlat@htxraudalat.vn",
        "credit_limit_vnd": 250_000_000,
        "payment_term_days": 20,
    },
]

#: (customer_code, service_type, equipment_code, volume_tons, revenue, %cogs theo tung khoan)
ORDER_TEMPLATE: list[tuple[str, str, str | None, float, int, dict]] = [
    ("KH-001", "Cấp đông nhanh hải sản IQF", "CAP_DONG_01", 12.5, 125_000_000, {"d": 0.085, "r": 0.055, "l": 0.14, "m": 0.06, "o": 0.11}),
    ("KH-001", "Bảo quản kho đông -25°C", "KHO_DONG_01", 48.0, 96_000_000, {"d": 0.11, "r": 0.04, "l": 0.12, "m": 0.05, "o": 0.13}),
    ("KH-002", "Cho thuê kho mát nông sản", "KHO_MAT_01", 32.0, 85_000_000, {"d": 0.10, "r": 0.035, "l": 0.11, "m": 0.045, "o": 0.12}),
    ("KH-003", "Bảo quản kem & sữa (+2°C)", "KHO_MAT_01", 18.0, 54_000_000, {"d": 0.095, "r": 0.03, "l": 0.13, "m": 0.04, "o": 0.12}),
    ("KH-004", "Cung cấp hơi công nghiệp", "LO_HOI_01", None, 72_000_000, {"d": 0.02, "r": 0.0, "l": 0.09, "m": 0.07, "o": 0.10}),
    ("KH-005", "Cho thuê kho đông -22°C", "KHO_DONG_02", 26.0, 115_000_000, {"d": 0.12, "r": 0.045, "l": 0.11, "m": 0.05, "o": 0.12}),
    ("KH-006", "Bảo quản rau hoa ngắn hạn", "KHO_MAT_01", 9.5, 28_000_000, {"d": 0.10, "r": 0.03, "l": 0.14, "m": 0.04, "o": 0.13}),
]


def seed_customers(session: Session) -> dict[str, Customer]:
    existing = {c.code: c for c in session.scalars(select(Customer))}
    for spec in CUSTOMER_SPEC:
        if spec["code"] in existing:
            continue
        customer = Customer(is_active=True, **spec)
        session.add(customer)
        existing[spec["code"]] = customer
    session.flush()
    return existing


def seed_monthly_targets(session: Session) -> int:
    if session.scalars(select(MonthlyTarget).limit(1)).first():
        return 0
    now = utcnow()
    # offset thang so voi thang hien tai
    plan = [
        (0, 4_000_000_000, 42.0, "Thang cao diem vu hai san"),
        (-1, 3_800_000_000, 41.5, None),
        (-2, 3_500_000_000, 40.0, "Thap diem - bao tri lon lo hoi 02"),
    ]
    current_start, _ = month_bounds(now)
    for offset, revenue, margin, note in plan:
        moment = current_start
        for _ in range(abs(offset)):
            moment = month_bounds(moment - timedelta(days=1))[0]
        session.add(
            MonthlyTarget(
                year=moment.year,
                month=moment.month,
                revenue_target_vnd=revenue,
                gross_margin_target_pct=margin,
                note=note,
            )
        )
    session.flush()
    return len(plan)


def seed_orders(
    session: Session, customers: dict[str, Customer], equipment: list[Equipment], rng: random.Random
) -> list[ServiceOrder]:
    if session.scalars(select(ServiceOrder).limit(1)).first():
        return []
    eq_by_code = {e.code: e for e in equipment}
    now = utcnow()
    orders: list[ServiceOrder] = []
    seq = 100

    # 45 ngay lich su + hom nay, mo ban kinh doanh theo thang
    for days_ago in range(45, -1, -1):
        day_start = (now - timedelta(days=days_ago)).replace(hour=7, minute=30, second=0, microsecond=0)
        n_orders = rng.choice([1, 1, 2, 2, 3])
        for _ in range(n_orders):
            code_cust, service_type, eq_code, volume, revenue, cogs_pct = rng.choice(ORDER_TEMPLATE)
            customer = customers.get(code_cust)
            if customer is None:
                continue
            seq += 1
            scale = rng.uniform(0.65, 1.35)
            revenue_vnd = int(round(revenue * scale / 10_000) * 10_000)
            volume_tons = round(volume * scale, 2) if volume else None

            # Chi phi dien cua don hang thue kho lay tu thiet bi gan voi don
            order = ServiceOrder(
                code=f"ORD-{seq:04d}",
                customer_id=customer.id,
                equipment_id=eq_by_code[eq_code].id if eq_code in eq_by_code else None,
                service_type=service_type,
                volume_tons=volume_tons,
                started_at=day_start + timedelta(hours=rng.randint(0, 9)),
                status=OrderStatus.IN_PROGRESS.value if days_ago == 0 else OrderStatus.COMPLETED.value,
                revenue_vnd=revenue_vnd,
                electricity_cost_vnd=int(round(revenue_vnd * cogs_pct["d"])),
                refrigerant_cost_vnd=int(round(revenue_vnd * cogs_pct["r"])),
                labor_cost_vnd=int(round(revenue_vnd * cogs_pct["l"])),
                maintenance_cost_vnd=int(round(revenue_vnd * cogs_pct["m"])),
                overhead_cost_vnd=int(round(revenue_vnd * cogs_pct["o"])),
            )
            order.ended_at = (
                None if days_ago == 0 else order.started_at + timedelta(hours=rng.randint(6, 72))
            )
            session.add(order)
            orders.append(order)

    session.flush()
    return orders


def seed_receivables(
    session: Session, orders: list[ServiceOrder], rng: random.Random
) -> int:
    if session.scalars(select(Receivable).limit(1)).first():
        return 0
    now = utcnow()
    inv_seq = 2400
    created = 0

    # Kich ban tuoi no: phan bo de ca 5 bracket deu co so du
    # (age_days, da thanh toan chua, ty le da tra)
    scenario: list[tuple[int, bool, float]] = [
        (0, False, 0.0),     # trong han
        (8, False, 0.0),
        (22, False, 0.0),    # 1-30
        (38, False, 0.25),   # 31-60, tra mot phan
        (55, False, 0.0),    # 31-60
        (78, False, 0.0),    # 61-90
        (112, False, 0.0),   # >90
    ]
    # Don da hoan tat, co hoa don
    completed = [o for o in orders if o.status == OrderStatus.COMPLETED.value]
    if not completed:
        return 0

    def _pick(index_from_end: int) -> ServiceOrder | None:
        """Lay don cach cuoi danh sach `index_from_end` buoc; None khi khong du lich su."""
        if index_from_end <= 0 or index_from_end > len(completed):
            return None
        return completed[-index_from_end]

    for idx, (age_days, paid, pay_ratio) in enumerate(scenario):
        order = _pick((idx + 1) * 3)
        if order is None:
            continue
        customer = order.customer
        inv_seq += 1
        issued = now - timedelta(days=age_days + customer.payment_term_days)
        due = issued + timedelta(days=customer.payment_term_days)
        paid_amount = int(round(order.revenue_vnd * pay_ratio / 1000) * 1000) if pay_ratio else 0
        settled = paid and paid_amount >= order.revenue_vnd
        session.add(
            Receivable(
                customer_id=customer.id,
                order_id=order.id,
                invoice_number=f"HD-{inv_seq}",
                amount_vnd=order.revenue_vnd,
                paid_amount_vnd=paid_amount,
                issued_at=issued,
                due_at=due,
                paid_at=due - timedelta(days=3) if settled else None,
                status=ReceivableStatus.PAID.value if settled else (
                    ReceivableStatus.PARTIAL.value if paid_amount else ReceivableStatus.OPEN.value
                ),
                note=None if age_days <= 30 else f"Da goi nhac no lan {1 + age_days // 30}, khach hen tra trong thang.",
            )
        )
        created += 1

    # Them hoa don DA THANH TOAN de ty le thu tien khong bi 0%
    for idx in range(12, 30, 3):
        order = _pick(idx)
        if order is None:
            continue
        inv_seq += 1
        issued = now - timedelta(days=idx + 20)
        session.add(
            Receivable(
                customer_id=order.customer_id,
                order_id=order.id,
                invoice_number=f"HD-{inv_seq}",
                amount_vnd=order.revenue_vnd,
                paid_amount_vnd=order.revenue_vnd,
                issued_at=issued,
                due_at=issued + timedelta(days=order.customer.payment_term_days),
                paid_at=issued + timedelta(days=rng.randint(5, 25)),
                status=ReceivableStatus.PAID.value,
            )
        )
        created += 1

    session.flush()
    return created


# --------------------------------------------------------------------------- #
# Billing cho khach thue kho (dung pipeline that)
# --------------------------------------------------------------------------- #
TENANT_METER_BASE = {
    "THUE-ANPHAT": 152_480.0,
    "THUE-HOANGGIA": 88_215.0,
}


def seed_billing_history(session: Session, equipment: list[Equipment], rng: random.Random) -> int:
    """Sinh 3 ky hoa don cho khach thue, chay qua `billing.build_invoice` that.

    Dung pipeline that => ky seed nay cung chinh la vong kiem thu cho TOU/idempotency.
    """
    if session.scalars(select(BilledInvoice).limit(1)).first():
        return 0

    settings = get_settings()
    rate = settings.service_rate_per_kwh or 3500
    now = utcnow()
    tenant_eq = {e.tenant_code: e for e in equipment if e.tenant_code}
    created = 0

    for tenant_code, item in tenant_eq.items():
        base = TENANT_METER_BASE.get(tenant_code, 100_000.0)
        for months_ago in (2, 1, 0):
            moment = utcnow().replace(day=1)
            for _ in range(months_ago):
                moment = month_bounds(moment - timedelta(days=1))[0]

            period_start, period_end = month_bounds(moment)
            if months_ago == 0:
                # Ky hien tai chua ket thuc: chi tinh den het hom qua
                period_end = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                if period_end <= period_start:
                    continue

            hours = (period_end - period_start).total_seconds() / 3600
            duty = rng.uniform(0.55, 0.75)
            delta = (item.rated_power_kw or 20.0) * duty * hours
            previous = base
            current = round(base + delta, 2)
            base = current

            billing.build_invoice(
                session,
                tenant_code=tenant_code,
                period_start=period_start,
                period_end=period_end,
                previous_kwh=previous,
                current_kwh=current,
                service_rate_per_kwh=rate,
                equipment_id=item.id,
                rated_power_kw=item.rated_power_kw,
                entity_id=item.meter_entity_id,
                source="SEED",
            )
            created += 1

    session.flush()
    return created


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def seed_if_empty(session: Session, force: bool = False) -> dict:
    """Seed khi DB rong. Tra ve thong ke de log/doc qua API."""
    has_data = session.scalars(select(Equipment).limit(1)).first() is not None
    if has_data and not force:
        return {"seeded": False, "reason": "Da co du lieu, bo qua seed."}

    rng = random.Random(RANDOM_SEED)
    settings = get_settings()

    users = seed_users(session, settings.seed_demo_user_password)
    bands = seed_tariff_bands(session)
    equipment = seed_equipment(session)
    rules = seed_alarm_rules(session)
    samples = seed_telemetry(session, equipment, rng)
    session.commit()

    customers = seed_customers(session)
    targets = seed_monthly_targets(session)
    orders = seed_orders(session, customers, equipment, rng)
    receivables = seed_receivables(session, orders, rng)
    session.commit()

    invoices = seed_billing_history(session, equipment, rng)
    session.commit()

    history = seed_alert_history(session, list(session.scalars(select(User))))
    session.commit()
    raised = seed_alerts_from_telemetry(session, equipment)
    session.commit()

    return {
        "seeded": True,
        "users": len(users),
        "tariff_bands": bands,
        "equipment": len(equipment),
        "alarm_rules": rules,
        "telemetry_samples": samples,
        "customers": len(customers),
        "monthly_targets": targets,
        "service_orders": len(orders),
        "receivables": receivables,
        "billed_invoices": invoices,
        "alerts_history": history,
        "alerts_raised": raised,
    }


def reset(session: Session) -> None:
    """Xoa het du lieu nghiep vu (giu schema). Dung cho test/demo lai tu dau."""
    for model in (
        Alert,
        BilledInvoice,
        MeterReading,
        Receivable,
        ServiceOrder,
        MonthlyTarget,
        Customer,
        TelemetrySample,
        AlarmRule,
        Equipment,
        TariffBand,
        User,
    ):
        session.query(model).delete()
    session.commit()
