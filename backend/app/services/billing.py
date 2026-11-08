"""Billing dien nang theo bieu gia EVN gio (TOU 3 muc).

Cong thuc theo thiet ke Huong B:
    Tien dien = delta_kWh x Don gia EVN (theo tung khung gio) + Phi quan ly

Bon loi nghiep vu duoc sua o day:
1. Tinh tien theo DELTA kWh cua ky, khong phai chi so cong to TICH LUY.
2. Ap gia theo 3 khung gio (cao diem / binh thuong / thap diem), khong mot gia duy nhat.
3. Tu choi (khong "boc" ra so lieu) khi du lieu doc cong to khong hop le.
4. Tong kWh chia theo 3 khung gio LUON bang delta cua cong to hoa don: telemetry chi
   quyet dinh ty le giua cac khung, khong duoc quyet dinh tong so tien.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BilledInvoice, MeterReading, TariffBand, TariffBandCode, TelemetrySample
from ..timeutil import utctoday

#: He so an toan khi chan delta kWh bat thuong so voi cong suat dat cua thiet bi
PLAUSIBILITY_FACTOR = 1.5

#: Sai lech kWh chap nhan duoc giua tong telemetry do duoc va delta cua cong to hoa don.
#: Nam trong nguong nay thi coi nhu telemetry da phu het ky, chi con le lam tron.
SPLIT_RECONCILE_TOLERANCE_KWH = 0.5


class BillingError(Exception):
    """Loi du lieu billing. Goi len HTTP 422/503, KHONG duoc am tham tinh ra so lieu sai."""

    def __init__(self, message: str, code: str = "invalid_reading") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# --------------------------------------------------------------------------- #
# Bieu gia
# --------------------------------------------------------------------------- #
def active_bands(session: Session, at: date | datetime | None = None) -> list[TariffBand]:
    """Lay bo khung gio co hieu luc tai thoi diem `at` (lay effective_from gan nhat).

    Mac dinh la hom nay theo UTC (`utctoday()`), KHONG theo `date.today()`: toan bo he
    thong luu datetime naive-UTC (xem timeutil.py), nen lay ngay theo gio may chu thi
    bieu gia bi lech dung luc nua dem - va lech theo mui gio dat server, tuc la dev o
    VN (+07) va prod dat o UTC se chon hai bo khung gio khac nhau trong 7 tieng moi ngay.
    """
    on = (at.date() if isinstance(at, datetime) else at) or utctoday()
    stmt = (
        select(TariffBand)
        .where(TariffBand.is_active.is_(True), TariffBand.effective_from <= on)
        .order_by(TariffBand.effective_from.desc())
    )
    latest: dict[tuple[str, int, str], TariffBand] = {}
    for band in session.scalars(stmt):
        key = (band.code, band.start_minute, band.days)
        latest.setdefault(key, band)
    return sorted(latest.values(), key=lambda b: b.start_minute)


def band_prices(bands: list[TariffBand]) -> dict[str, int]:
    """Gia theo ma khung gio. Mot ma co the co nhieu dong gio -> chung mot gia."""
    prices: dict[str, list[int]] = {}
    for band in bands:
        prices.setdefault(band.code, []).append(band.price_vnd_per_kwh)
    resolved = {code: max(vals) for code, vals in prices.items()}
    if TariffBandCode.NORMAL.value not in resolved and resolved:
        # Can co gia binh thuong lam gia fallback cho khoang thoi gian khop band nao
        resolved[TariffBandCode.NORMAL.value] = min(resolved.values())
    return resolved


def band_intervals(start: datetime, end: datetime, band: TariffBand) -> list[tuple[datetime, datetime]]:
    """Cac khoang thoi gian thuc te cua `band` nam trong [start, end]. Chinh xac, khong uoc luong."""
    allowed_days = None if band.days == "*" else {int(d) for d in band.days.split(",") if d.strip()}
    out: list[tuple[datetime, datetime]] = []
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        if allowed_days is None or day.isoweekday() in allowed_days:
            seg_start = max(day + timedelta(minutes=band.start_minute), start)
            seg_end = min(day + timedelta(minutes=band.end_minute), end)
            if seg_end > seg_start:
                out.append((seg_start, seg_end))
        day += timedelta(days=1)
    return out


def band_minutes(start: datetime, end: datetime, bands: list[TariffBand]) -> dict[str, float]:
    """So phut cua ky roi vao tung khung gio."""
    totals = {code.value: 0.0 for code in TariffBandCode}
    for band in bands:
        minutes = sum((e - s).total_seconds() / 60 for s, e in band_intervals(start, end, band))
        totals[band.code] += minutes
    return totals


def band_of(moment: datetime, bands: list[TariffBand]) -> str:
    for band in bands:
        if band.applies_to(moment):
            return band.code
    return TariffBandCode.NORMAL.value


# --------------------------------------------------------------------------- #
# Doc cong to -> delta kWh
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReadingValidation:
    delta_kwh: float
    warnings: list[str]


def validate_delta(
    previous_kwh: float | None,
    current_kwh: float,
    rated_power_kw: float | None = None,
    period_hours: float | None = None,
) -> ReadingValidation:
    """Delta kWh tu 2 lan doc cong to. Fail-fast khi du lieu vo ly.

    KHONG bao gio tra ve 0 hay mot gia tri "doan" - do la loi billing nghiem trong.
    """
    if current_kwh is None:
        raise BillingError("Thieu chi so cong to hien tai.", code="missing_reading")
    if previous_kwh is None:
        raise BillingError(
            "Chua co chi so cong to ky truoc lam goc. Khong the tinh delta kWh - "
            "hay nhap chi so dau ky truoc khi xuat hoa don.",
            code="missing_baseline",
        )

    delta = current_kwh - previous_kwh
    warnings: list[str] = []

    if delta < 0:
        raise BillingError(
            f"Chi so cong to tụt: ky truoc {previous_kwh:.2f} kWh > ky nay {current_kwh:.2f} kWh. "
            "Co the do thay cong to hoac loi cam bien. Can xu ly thu cong.",
            code="counter_rolled_back",
        )

    if delta == 0:
        warnings.append("Delta kWh = 0: thiet bi khong van hanh trong ky, hoac cam bien bi dung.")

    if rated_power_kw and period_hours and period_hours > 0:
        ceiling = rated_power_kw * period_hours * PLAUSIBILITY_FACTOR
        if delta > ceiling:
            raise BillingError(
                f"Delta {delta:.2f} kWh vuot tran vat ly {ceiling:.2f} kWh "
                f"(cong suat dat {rated_power_kw:g} kW x {period_hours:g} h x {PLAUSIBILITY_FACTOR}). "
                "Nhay so bat thuong, tu choi xuat hoa don.",
                code="implausible_delta",
            )

    return ReadingValidation(delta_kwh=round(delta, 3), warnings=warnings)


@dataclass(frozen=True)
class MeasuredSplit:
    """Phan chia kWh DO DUOC tu telemetry, kem doan thoi gian ma telemetry thuc su phu."""

    kwh: dict[str, float]
    covered_seconds: float
    sample_count: int


def measured_split(
    session: Session,
    equipment_id: int,
    start: datetime,
    end: datetime,
    bands: list[TariffBand],
) -> MeasuredSplit | None:
    """Chia delta kWh that theo 3 khung gio, dung chi so cong to tich luy trong telemetry.

    Tra ve None khi khong du du lieu (can < 2 mau co energy_kwh_cumulative).

    `covered_seconds` la doan tu mau dau den mau cuoi. Telemetry co the chi phu MOT PHAN
    cua ky (edge agent mat ket noi, hoac ky con dang chay), nen tong o day khong duoc
    phep coi la tong kWh cua ca ky - phai doi chieu voi delta cua cong to hoa don.
    """
    stmt = (
        select(TelemetrySample)
        .where(
            TelemetrySample.equipment_id == equipment_id,
            TelemetrySample.ts >= start,
            TelemetrySample.ts <= end,
            TelemetrySample.energy_kwh_cumulative.is_not(None),
        )
        .order_by(TelemetrySample.ts)
    )
    samples = list(session.scalars(stmt))
    if len(samples) < 2:
        return None

    split = {code.value: 0.0 for code in TariffBandCode}
    for prev, cur in zip(samples, samples[1:]):
        delta = cur.energy_kwh_cumulative - prev.energy_kwh_cumulative
        if delta < 0:
            # Cong to bi thay/reset giua ky: bo qua khoang nay, khong am tham bu dap
            continue
        midpoint = prev.ts + (cur.ts - prev.ts) / 2
        split[band_of(midpoint, bands)] += delta
    return MeasuredSplit(
        kwh={code: round(kwh, 3) for code, kwh in split.items()},
        covered_seconds=(samples[-1].ts - samples[0].ts).total_seconds(),
        sample_count=len(samples),
    )


def split_from_telemetry(
    session: Session,
    equipment_id: int,
    start: datetime,
    end: datetime,
    bands: list[TariffBand],
) -> dict[str, float] | None:
    """Phan chia kWh theo khung gio tu telemetry. Tra ve DUNG PHAN DO DUOC, khong tu suy ra ca ky.

    Dung cho bao cao tieu thu noi bo (`equipment_energy_kwh`). Con de tinh hoa don thi
    phai di qua `reconcile_split`: tong o day co the nho hon nhieu so voi delta that cua
    cong to khi telemetry khong phu het ky, va hoa don thi khong duoc phep tinh thieu.
    """
    measured = measured_split(session, equipment_id, start, end, bands)
    return measured.kwh if measured is not None else None


def split_from_hours(total_kwh: float, start: datetime, end: datetime, bands: list[TariffBand]) -> dict[str, float]:
    """UOC LUONG: phan bo delta kWh theo ty le so gio cua tung khung gio.

    Chi dung khi khong co du lieu telemetry theo phut. Ket qua phai duoc danh dau
    split_method='hours_estimate' de nguoi dung biet day khong la so do thuc.
    """
    minutes = band_minutes(start, end, bands)
    covered = sum(minutes.values())
    if covered <= 0:
        return {TariffBandCode.NORMAL.value: round(total_kwh, 3)}
    split = {code: total_kwh * (mins / covered) for code, mins in minutes.items()}
    return {code: round(kwh, 3) for code, kwh in split.items()}


def _scale_split_to_total(split: dict[str, float], total_kwh: float) -> dict[str, float]:
    """Giun hinh dang da do ve dung `total_kwh`, va dam bao tong 3 khung bang `total_kwh` that su.

    Lam tron 3 so rieng re con le vai phan nghin kWh so voi tong; phan le duoc cong vao
    khung lon nhat de `sum(kwh_by_band) == total_kwh` dung bang so, khong chi "gan bang".
    """
    measured = sum(split.values())
    if measured <= 0:
        return {code.value: 0.0 for code in TariffBandCode}
    factor = total_kwh / measured
    scaled = {code: round(kwh * factor, 3) for code, kwh in split.items()}
    residue = round(round(total_kwh, 3) - sum(scaled.values()), 3)
    if abs(residue) >= 0.001:
        largest = max(scaled, key=lambda code: scaled[code])
        scaled[largest] = round(scaled[largest] + residue, 3)
    return scaled


@dataclass(frozen=True)
class SplitDecision:
    """Cach da chia delta kWh cua ky theo 3 khung gio, kem phuong phap de khai bao trung thuc."""

    kwh: dict[str, float]
    method: str
    warnings: list[str]
    covered_seconds: float | None


def reconcile_split(
    session: Session,
    equipment_id: int | None,
    delta_kwh: float,
    period_start: datetime,
    period_end: datetime,
    bands: list[TariffBand],
) -> SplitDecision:
    """Chia delta kWh cua cong to hoa don theo 3 khung gio EVN.

    `delta_kwh` la so DUY NHAT duoc phep ra tien: no den tu 2 lan doc cong to cua ca ky.
    Telemetry theo phut chi dung de lay HINH DANG (ty le giua cac khung gio). Vi vay moi
    nhanh deu phai thoa `sum(split) == delta_kwh`. Truoc day hoa don lay nguyen xi phan
    telemetry do duoc, nen khi telemetry chi phu vai gio trong ky thi tien dien tinh thieu
    hon hang chuc lan so voi dong ho - khach hang bi tinh thieu ma khong he co canh bao.

    Ba nhanh, deu ghi ro phuong phap de nguoi dung biet so nao la do, so nao la suy ra:
      telemetry         telemetry phu het ky, tong do duoc khop delta cong to
      telemetry_scaled  telemetry chi phu mot phan -> giun ty le da do len delta that
      hours_estimate    khong co telemetry dung duoc -> chia theo ty le so gio cua khung
    """
    fallback = SplitDecision(
        kwh=split_from_hours(delta_kwh, period_start, period_end, bands),
        method="hours_estimate",
        warnings=[],
        covered_seconds=None,
    )
    if equipment_id is None:
        return fallback

    measured = measured_split(session, equipment_id, period_start, period_end, bands)
    if measured is None:
        return fallback

    measured_total = sum(measured.kwh.values())
    if measured_total <= 0:
        # Telemetry noi "khong tieu thu" trong khi cong to hoa don van chay: hai nguon mau
        # thuan nhau. Khong duoc lay hinh dang toan 0 (tien dien = 0), ve uoc luong theo gio.
        return fallback

    if abs(delta_kwh - measured_total) <= SPLIT_RECONCILE_TOLERANCE_KWH:
        method, warnings = "telemetry", []
    else:
        covered_hours = measured.covered_seconds / 3600
        period_hours = (period_end - period_start).total_seconds() / 3600
        pct = (covered_hours / period_hours * 100) if period_hours > 0 else 0.0
        method = "telemetry_scaled"
        warnings = [
            f"Telemetry chi phu {covered_hours:g} / {period_hours:g} gio cua ky ({pct:.1f}%): "
            f"do duoc {measured_total:,.2f} kWh trong khi cong to hoa don tang {delta_kwh:,.2f} kWh. "
            "Tong kWh va tong tien lay theo cong to; ty le giua cac khung gio la SUY RA tu "
            "phan do duoc, khong phai so do truc tiep cho ca ky.",
        ]

    return SplitDecision(
        kwh=_scale_split_to_total(measured.kwh, delta_kwh),
        method=method,
        warnings=warnings,
        covered_seconds=measured.covered_seconds,
    )


# --------------------------------------------------------------------------- #
# Tinh hoa don
# --------------------------------------------------------------------------- #
def electricity_cost(split_kwh: dict[str, float], prices: dict[str, int]) -> int:
    normal_price = prices.get(TariffBandCode.NORMAL.value, 0)
    total = 0
    for code, kwh in split_kwh.items():
        total += int(round(kwh * prices.get(code, normal_price)))
    return total


def build_invoice(
    session: Session,
    tenant_code: str,
    period_start: datetime,
    period_end: datetime,
    previous_kwh: float | None,
    current_kwh: float,
    service_rate_per_kwh: int,
    equipment_id: int | None = None,
    rated_power_kw: float | None = None,
    entity_id: str | None = None,
    source: str = "HA",
) -> dict:
    """Tinh toan hoa don tu CHI SO TICH LUY dau/cuoi ky.

    Delta kWh duoc tinh o day (khong nhan delta tu ben goi) va duoc luu lai thanh
    MeterReading de ky sau co goc so sanh. IDEMPOTENT theo (tenant_code, period_start, period_end).
    """
    if period_end <= period_start:
        raise BillingError("Ky billing khong hop le: period_end phai sau period_start.", code="bad_period")

    existing = session.scalars(
        select(BilledInvoice).where(
            BilledInvoice.tenant_code == tenant_code,
            BilledInvoice.period_start == period_start,
            BilledInvoice.period_end == period_end,
        )
    ).first()
    if existing is not None:
        return _invoice_payload(existing, duplicated=True)

    period_hours = (period_end - period_start).total_seconds() / 3600
    validation = validate_delta(previous_kwh, current_kwh, rated_power_kw, period_hours)
    delta_kwh = validation.delta_kwh

    bands = active_bands(session, period_end)
    if not bands:
        raise BillingError("Chua cau hinh bieu gia EVN (bang tariff_bands rong).", code="no_tariff")
    prices = band_prices(bands)

    split_decision = reconcile_split(session, equipment_id, delta_kwh, period_start, period_end, bands)
    split = split_decision.kwh
    warnings = [*validation.warnings, *split_decision.warnings]

    elec_vnd = electricity_cost(split, prices)
    service_vnd = int(round(delta_kwh * service_rate_per_kwh))
    total_vnd = elec_vnd + service_vnd

    # Luu lan doc cong to lam goc cho ky ke tiep. Trung khoa thi cap nhat, khong tao ban ghi moi.
    reading = session.scalars(
        select(MeterReading).where(
            MeterReading.tenant_code == tenant_code,
            MeterReading.period_start == period_start,
            MeterReading.period_end == period_end,
        )
    ).first()
    if reading is None:
        reading = MeterReading(
            tenant_code=tenant_code,
            equipment_id=equipment_id,
            entity_id=entity_id,
            period_start=period_start,
            period_end=period_end,
            reading_start_kwh=previous_kwh,
            reading_end_kwh=current_kwh,
            delta_kwh=delta_kwh,
            source=source,
            peak_kwh=split.get(TariffBandCode.PEAK.value, 0.0),
            normal_kwh=split.get(TariffBandCode.NORMAL.value, 0.0),
            off_peak_kwh=split.get(TariffBandCode.OFF_PEAK.value, 0.0),
        )
        session.add(reading)
        session.flush()
    else:
        # Doc lai cong to cua cung ky nay: cap nhat ca chi so lan phan chia theo khung gio,
        # neu khong thi meter_readings se lech voi billed_invoices vua tinh lai.
        reading.reading_end_kwh = current_kwh
        reading.delta_kwh = delta_kwh
        reading.peak_kwh = split.get(TariffBandCode.PEAK.value, 0.0)
        reading.normal_kwh = split.get(TariffBandCode.NORMAL.value, 0.0)
        reading.off_peak_kwh = split.get(TariffBandCode.OFF_PEAK.value, 0.0)
        session.flush()

    invoice = BilledInvoice(
        tenant_code=tenant_code,
        period_start=period_start,
        period_end=period_end,
        meter_reading_id=reading.id,
        total_kwh=delta_kwh,
        peak_kwh=split.get(TariffBandCode.PEAK.value, 0.0),
        normal_kwh=split.get(TariffBandCode.NORMAL.value, 0.0),
        off_peak_kwh=split.get(TariffBandCode.OFF_PEAK.value, 0.0),
        electricity_vnd=elec_vnd,
        service_fee_vnd=service_vnd,
        total_vnd=total_vnd,
        breakdown={
            "split_method": split_decision.method,
            "prices_vnd_per_kwh": prices,
            "reading_start_kwh": previous_kwh,
            "reading_end_kwh": current_kwh,
            "service_rate_per_kwh": service_rate_per_kwh,
            # Telemetry phu bao nhieu gi trong ky - de nguoi kiem toan biet phan chia theo
            # khung gio la so do truc tiep hay la suy ra. None = ky nay khong co telemetry.
            "telemetry_covered_hours": (
                round(split_decision.covered_seconds / 3600, 3)
                if split_decision.covered_seconds is not None
                else None
            ),
            "period_hours": round(period_hours, 3),
            "warnings": warnings,
        },
    )
    session.add(invoice)
    session.flush()
    return _invoice_payload(invoice, duplicated=False)


def _invoice_payload(invoice: BilledInvoice, duplicated: bool) -> dict:
    return {
        "id": invoice.id,
        "tenant_code": invoice.tenant_code,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "total_kwh": invoice.total_kwh,
        "kwh_by_band": {
            TariffBandCode.PEAK.value: invoice.peak_kwh,
            TariffBandCode.NORMAL.value: invoice.normal_kwh,
            TariffBandCode.OFF_PEAK.value: invoice.off_peak_kwh,
        },
        "electricity_vnd": invoice.electricity_vnd,
        "service_fee_vnd": invoice.service_fee_vnd,
        "total_vnd": invoice.total_vnd,
        "external_invoice_id": invoice.external_invoice_id,
        "breakdown": invoice.breakdown,
        "issued_at": invoice.issued_at.isoformat() if invoice.issued_at else None,
        "duplicated_call": duplicated,
    }


# --------------------------------------------------------------------------- #
# Phan tich dich chuyen phu tai (load shifting)
# --------------------------------------------------------------------------- #
def load_shift_analysis(split_kwh: dict[str, float], prices: dict[str, int], shift_pct: float = 0.2) -> dict:
    """Dich `shift_pct` phu tai tu gio cao diem sang gio thap diem -> tiet kiem bao nhieu.

    Day la con so that tinh tu bieu gia, khong phai "35%" viet chet trong UI.
    """
    peak_kwh = split_kwh.get(TariffBandCode.PEAK.value, 0.0)
    peak_price = prices.get(TariffBandCode.PEAK.value, 0)
    offpeak_price = prices.get(TariffBandCode.OFF_PEAK.value, 0)

    shifted_kwh = peak_kwh * max(0.0, min(1.0, shift_pct))
    saving_vnd = int(round(shifted_kwh * max(0, peak_price - offpeak_price)))
    baseline_vnd = electricity_cost(split_kwh, prices)

    return {
        "shift_pct": round(max(0.0, min(1.0, shift_pct)) * 100, 1),
        "shifted_kwh": round(shifted_kwh, 2),
        "saving_vnd": saving_vnd,
        "baseline_electricity_vnd": baseline_vnd,
        "saving_pct": round(saving_vnd / baseline_vnd * 100, 2) if baseline_vnd else 0.0,
        "peak_price_vnd_per_kwh": peak_price,
        "off_peak_price_vnd_per_kwh": offpeak_price,
        "price_gap_vnd_per_kwh": peak_price - offpeak_price,
    }


# --------------------------------------------------------------------------- #
# Tieu thu dien cua chinh nha may (chi phi dien noi bo)
# --------------------------------------------------------------------------- #
def equipment_energy_kwh(
    session: Session,
    equipment_id: int,
    start: datetime,
    end: datetime,
    bands: list[TariffBand],
) -> tuple[float, dict[str, float], str]:
    """Dien nang tieu thu cua mot thiet bi trong [start, end].

    Uu tien 1: delta chi so cong to tich luy (chinh xac nhat).
    Uu tien 2: tich phan hinh thang cong suat N_e theo thoi gian.
    Tra ve (tong_kwh, chia_theo_khung_gio, phuong_phap).
    """
    empty = {code.value: 0.0 for code in TariffBandCode}

    cumulative = split_from_telemetry(session, equipment_id, start, end, bands)
    if cumulative is not None and sum(cumulative.values()) > 0:
        return round(sum(cumulative.values()), 3), cumulative, "meter_delta"

    stmt = (
        select(TelemetrySample)
        .where(
            TelemetrySample.equipment_id == equipment_id,
            TelemetrySample.ts >= start,
            TelemetrySample.ts <= end,
            TelemetrySample.power_kw.is_not(None),
        )
        .order_by(TelemetrySample.ts)
    )
    samples = list(session.scalars(stmt))
    if len(samples) < 2:
        return 0.0, empty, "no_data"

    split = dict(empty)
    total = 0.0
    for prev, cur in zip(samples, samples[1:]):
        hours = (cur.ts - prev.ts).total_seconds() / 3600
        if hours <= 0:
            continue
        kwh = (prev.power_kw + cur.power_kw) / 2 * hours
        total += kwh
        midpoint = prev.ts + (cur.ts - prev.ts) / 2
        split[band_of(midpoint, bands)] += kwh

    return round(total, 3), {k: round(v, 3) for k, v in split.items()}, "power_integration"


def energy_cost_report(
    session: Session,
    start: datetime,
    end: datetime,
    equipment_ids: list[int] | None = None,
) -> dict:
    """Tong hop chi phi dien noi bo cua nha may trong mot khoang thoi gian."""
    from ..models import Equipment

    bands = active_bands(session, end)
    prices = band_prices(bands)

    if equipment_ids is None:
        equipment_ids = list(session.scalars(select(Equipment.id).where(Equipment.is_active.is_(True))))

    total_kwh = 0.0
    total_vnd = 0
    split = {code.value: 0.0 for code in TariffBandCode}
    per_equipment: list[dict] = []
    methods: set[str] = set()

    for equipment_id in equipment_ids:
        kwh, band_split, method = equipment_energy_kwh(session, equipment_id, start, end, bands)
        methods.add(method)
        cost_vnd = electricity_cost(band_split, prices)
        total_kwh += kwh
        total_vnd += cost_vnd
        for code, value in band_split.items():
            split[code] = split.get(code, 0.0) + value
        if kwh > 0:
            equipment = session.get(Equipment, equipment_id)
            per_equipment.append(
                {
                    "equipment_code": equipment.code if equipment else str(equipment_id),
                    "equipment_name": equipment.name if equipment else "",
                    "kwh": kwh,
                    "cost_vnd": cost_vnd,
                    "method": method,
                }
            )

    per_equipment.sort(key=lambda row: row["cost_vnd"], reverse=True)

    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "total_kwh": round(total_kwh, 2),
        "total_cost_vnd": total_vnd,
        "kwh_by_band": {code: round(value, 2) for code, value in split.items()},
        "prices_vnd_per_kwh": prices,
        "method": "mixed" if len(methods) > 1 else next(iter(methods), "no_data"),
        "shift_analysis": load_shift_analysis(split, prices),
        "top_consumers": per_equipment[:10],
    }
