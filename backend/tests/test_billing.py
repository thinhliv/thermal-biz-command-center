"""Nghiep vu billing: delta kWh (khong phai chi so tich luy), EVN TOU 3 khung gio,
fail-fast khi doc cong to vo ly, va idempotency theo (tenant, ky).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BilledInvoice,
    Equipment,
    EquipmentKind,
    MeterReading,
    TariffBand,
    TariffBandCode,
    TelemetrySample,
)
from app.seed import EVN_PRICES
from app.services import billing
from app.services.billing import BillingError
from app.timeutil import month_bounds, utcnow


def _period() -> tuple[datetime, datetime]:
    """Ky billing 1 thang da ket thuc (thang truoc)."""
    return month_bounds(utcnow() - timedelta(days=45))


def _bands(session: Session) -> list[TariffBand]:
    bands = billing.active_bands(session)
    assert bands, "Fixture `tariff` phai nap bieu gia EVN"
    return bands


@pytest.fixture()
def probe(tariff: Session) -> Equipment:
    """TelemetrySample.equipment_id la FK NOT NULL -> can mot thiet bi that."""
    item = Equipment(
        code="PROBE_KHO",
        name="Kho probe cho test billing",
        kind=EquipmentKind.COLD_ROOM.value,
        rated_power_kw=40.0,
        is_active=True,
    )
    tariff.add(item)
    tariff.commit()
    return item


def _add_meter(tariff: Session, equipment_id: int, readings: list[tuple[int, float]]) -> None:
    """Ghi cac moc (so phut lech tu 09:00 thu Tu, chi so cong to tich luy)."""
    start = datetime(2026, 1, 7, 9, 0)
    for offset_min, cumulative in readings:
        tariff.add(
            TelemetrySample(
                equipment_id=equipment_id,
                ts=start + timedelta(minutes=offset_min),
                power_kw=40.0,
                energy_kwh_cumulative=cumulative,
            )
        )
    tariff.commit()


# --------------------------------------------------------------------------- #
# Doc cong to -> delta kWh
# --------------------------------------------------------------------------- #
def test_thieu_chi_so_goc_phai_bao_loi_khong_duoc_doan() -> None:
    """Ky dau tien chua co goc: TU CHOI xuat hoa don, khong am tham lay current lam delta."""
    with pytest.raises(BillingError) as exc:
        billing.validate_delta(None, 1000.0)
    assert exc.value.code == "missing_baseline"


def test_cong_to_tut_phai_bao_loi() -> None:
    with pytest.raises(BillingError) as exc:
        billing.validate_delta(5000.0, 4800.0)
    assert exc.value.code == "counter_rolled_back"


def test_delta_vuot_tran_vat_ly_bi_tu_choi() -> None:
    """40 kW x 24 h x 1.5 = 1440 kWh la tran. Nhay so 99999 kWh la loi cam bien."""
    with pytest.raises(BillingError) as exc:
        billing.validate_delta(1000.0, 100_999.0, rated_power_kw=40.0, period_hours=24)
    assert exc.value.code == "implausible_delta"


def test_delta_hop_le_duoi_tran_vat_ly() -> None:
    result = billing.validate_delta(1000.0, 1400.0, rated_power_kw=40.0, period_hours=24)
    assert result.delta_kwh == 400.0
    assert result.warnings == []


def test_delta_bang_khong_duoc_phep_am_tham() -> None:
    result = billing.validate_delta(1000.0, 1000.0)
    assert result.delta_kwh == 0.0
    assert result.warnings, "Delta 0 phai canh bao: thiet bi dung hoac cam bien chet"


# --------------------------------------------------------------------------- #
# Bieu gio EVN (TOU)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        # 2026-01-07 la thu Tu, 2026-01-10 thu Bay, 2026-01-11 chu Nhat
        (datetime(2026, 1, 7, 10, 0), TariffBandCode.PEAK),      # 09:30-11:30
        (datetime(2026, 1, 7, 18, 30), TariffBandCode.PEAK),     # 17:00-20:00
        (datetime(2026, 1, 7, 12, 0), TariffBandCode.NORMAL),    # 11:30-17:00
        (datetime(2026, 1, 7, 20, 30), TariffBandCode.NORMAL),   # 20:00-22:00
        (datetime(2026, 1, 7, 23, 0), TariffBandCode.OFF_PEAK),  # 22:00-24:00
        (datetime(2026, 1, 7, 2, 0), TariffBandCode.OFF_PEAK),   # 00:00-04:00
        (datetime(2026, 1, 7, 5, 0), TariffBandCode.NORMAL),     # 04:00-09:30
        (datetime(2026, 1, 7, 9, 29), TariffBandCode.NORMAL),    # ranh: chua vao cao diem
        (datetime(2026, 1, 7, 9, 30), TariffBandCode.PEAK),      # ranh: bat dau cao diem
        (datetime(2026, 1, 10, 18, 0), TariffBandCode.PEAK),     # thu Bay van co cao diem
        # CHU NHAT: EVN khong tinh gio cao diem
        (datetime(2026, 1, 11, 10, 0), TariffBandCode.NORMAL),
        (datetime(2026, 1, 11, 18, 0), TariffBandCode.NORMAL),
        (datetime(2026, 1, 11, 23, 30), TariffBandCode.OFF_PEAK),
        (datetime(2026, 1, 11, 1, 0), TariffBandCode.OFF_PEAK),
    ],
)
def test_bieu_gio_evn(tariff: Session, moment: datetime, expected: TariffBandCode) -> None:
    assert billing.band_of(moment, _bands(tariff)) == expected.value


def test_bieu_gia_seed_dung_3_muc(tariff: Session) -> None:
    prices = billing.band_prices(_bands(tariff))
    assert prices == {code.value: value for code, value in EVN_PRICES.items()}
    assert prices["PEAK"] > prices["NORMAL"] > prices["OFF_PEAK"]


def test_bieu_gio_phu_kin_du_24h(tariff: Session) -> None:
    """Thieu mot khung gio thi split_from_hours chia sai ty le va hoa don sai tien."""
    start = datetime(2026, 1, 7, 0, 0)
    minutes = billing.band_minutes(start, start + timedelta(days=1), _bands(tariff))
    assert sum(minutes.values()) == pytest.approx(24 * 60)
    assert minutes[TariffBandCode.PEAK.value] == pytest.approx(120 + 180)
    assert minutes[TariffBandCode.OFF_PEAK.value] == pytest.approx(240 + 120)


def test_chu_nhat_khong_co_gio_cao_diem(tariff: Session) -> None:
    start = datetime(2026, 1, 11, 0, 0)
    minutes = billing.band_minutes(start, start + timedelta(days=1), _bands(tariff))
    assert minutes[TariffBandCode.PEAK.value] == 0.0
    assert sum(minutes.values()) == pytest.approx(24 * 60)


# --------------------------------------------------------------------------- #
# build_invoice: TOU + idempotency
# --------------------------------------------------------------------------- #
def test_hoa_don_tinh_tien_dien_theo_tung_khung_gio(tariff: Session) -> None:
    start, end = _period()
    invoice = billing.build_invoice(
        tariff, "THUE-ANPHAT", start, end,
        previous_kwh=10_000.0, current_kwh=11_000.0,
        service_rate_per_kwh=3500, source="MANUAL",
    )
    tariff.commit()

    assert invoice["total_kwh"] == pytest.approx(1000.0)
    bands = invoice["kwh_by_band"]
    assert sum(bands.values()) == pytest.approx(1000.0, abs=0.5), "Tong 3 khung phai bang delta"
    assert all(value > 0 for value in bands.values()), "Ky 1 thang phai co du ca 3 khung gio"

    prices = billing.band_prices(_bands(tariff))
    expected_elec = sum(int(round(kwh * prices[code])) for code, kwh in bands.items())
    assert invoice["electricity_vnd"] == expected_elec
    assert invoice["service_fee_vnd"] == 1000 * 3500
    assert invoice["total_vnd"] == invoice["electricity_vnd"] + invoice["service_fee_vnd"]


def test_cung_kwh_gio_cao_diem_dat_hon_gio_thap_diem(tariff: Session) -> None:
    prices = billing.band_prices(_bands(tariff))
    peak_only = billing.electricity_cost({TariffBandCode.PEAK.value: 1000.0}, prices)
    offpeak_only = billing.electricity_cost({TariffBandCode.OFF_PEAK.value: 1000.0}, prices)
    normal_only = billing.electricity_cost({TariffBandCode.NORMAL.value: 1000.0}, prices)
    assert peak_only > normal_only > offpeak_only


def test_xuat_hoa_don_2_lan_la_idempotent(tariff: Session) -> None:
    """Connector goi lai (retry/network) khong duoc tao hoa don trung."""
    start, end = _period()
    kwargs = dict(
        tenant_code="THUE-HOANGGIA", period_start=start, period_end=end,
        previous_kwh=500.0, current_kwh=900.0, service_rate_per_kwh=3500, source="MANUAL",
    )
    first = billing.build_invoice(tariff, **kwargs)
    tariff.commit()
    second = billing.build_invoice(tariff, **kwargs)
    tariff.commit()

    assert second["duplicated_call"] is True
    assert second["id"] == first["id"]
    assert second["total_vnd"] == first["total_vnd"]
    assert tariff.scalar(select(func.count()).select_from(BilledInvoice)) == 1
    assert tariff.scalar(select(func.count()).select_from(MeterReading)) == 1


def test_hoa_don_luu_chi_so_cong_to_lam_goc_ky_sau(tariff: Session) -> None:
    start, end = _period()
    billing.build_invoice(
        tariff, "THUE-ANPHAT", start, end,
        previous_kwh=1000.0, current_kwh=1500.0, service_rate_per_kwh=3500, source="HA",
    )
    tariff.commit()
    reading = tariff.scalars(select(MeterReading).where(MeterReading.tenant_code == "THUE-ANPHAT")).one()
    assert reading.reading_start_kwh == 1000.0
    assert reading.reading_end_kwh == 1500.0
    assert reading.delta_kwh == pytest.approx(500.0)
    assert reading.source == "HA"
    assert reading.peak_kwh + reading.normal_kwh + reading.off_peak_kwh == pytest.approx(500.0, abs=0.5)


def test_ky_billing_nguoc_bao_loi(tariff: Session) -> None:
    start, end = _period()
    with pytest.raises(BillingError) as exc:
        billing.build_invoice(
            tariff, "THUE-ANPHAT", end, start,
            previous_kwh=0.0, current_kwh=10.0, service_rate_per_kwh=3500,
        )
    assert exc.value.code == "bad_period"


def test_khong_co_bieu_gia_thi_bao_loi_khong_xuat_hoa_don_0_dong(tariff: Session) -> None:
    tariff.query(TariffBand).delete()
    tariff.commit()
    start, end = _period()
    with pytest.raises(BillingError) as exc:
        billing.build_invoice(
            tariff, "THUE-ANPHAT", start, end,
            previous_kwh=0.0, current_kwh=100.0, service_rate_per_kwh=3500,
        )
    assert exc.value.code == "no_tariff"


def test_khong_co_telemetry_thi_uoc_luong_theo_gio_va_noi_ro(tariff: Session) -> None:
    """Phuong phap tinh phai duoc khai bao trung thuc de nguoi dung biet day la so uoc."""
    start, end = _period()
    invoice = billing.build_invoice(
        tariff, "THUE-ANPHAT", start, end,
        previous_kwh=0.0, current_kwh=720.0, service_rate_per_kwh=3500, equipment_id=None,
    )
    tariff.commit()
    assert invoice["breakdown"]["split_method"] == "hours_estimate"


# --------------------------------------------------------------------------- #
# Chia kWh theo 3 khung gio tu telemetry that
# --------------------------------------------------------------------------- #
def test_split_from_telemetry_dung_diem_giua_cua_khoang(tariff: Session, probe: Equipment) -> None:
    """Mau 09:00->10:00: diem giua 09:30 ranh gio -> phai tinh vao khung 09:30-11:30."""
    _add_meter(tariff, probe.id, [(0, 100.0), (60, 130.0)])
    start = datetime(2026, 1, 7, 9, 0)

    split = billing.split_from_telemetry(
        tariff, probe.id, start - timedelta(hours=1), start + timedelta(hours=2), _bands(tariff)
    )
    assert split is not None
    assert split[TariffBandCode.PEAK.value] == pytest.approx(30.0)
    assert split[TariffBandCode.NORMAL.value] == 0.0


def test_split_from_telemetry_bo_qua_doan_cong_to_tut(tariff: Session, probe: Equipment) -> None:
    """Cong to bi thay giua ky: bo qua khoang am, KHONG am tham bu dap."""
    _add_meter(tariff, probe.id, [(0, 100.0), (60, 80.0), (120, 110.0)])
    start = datetime(2026, 1, 7, 9, 0)

    split = billing.split_from_telemetry(
        tariff, probe.id, start, start + timedelta(hours=3), _bands(tariff)
    )
    assert split is not None
    total = sum(split.values())
    assert total == pytest.approx(30.0), "Chi tinh doan 80->110, bo doan 100->80"


def test_split_from_telemetry_tra_ve_none_khi_thieu_du_lieu(tariff: Session, probe: Equipment) -> None:
    _add_meter(tariff, probe.id, [(0, 5.0)])
    assert billing.split_from_telemetry(
        tariff, probe.id, datetime(2026, 1, 7), datetime(2026, 1, 8), _bands(tariff)
    ) is None


def test_build_invoice_dung_telemetry_khi_co_du_mau(tariff: Session, probe: Equipment) -> None:
    """Co telemetry that -> split_method='telemetry', khong phai uoc luong theo gio."""
    _add_meter(tariff, probe.id, [(0, 500.0), (60, 530.0), (120, 570.0)])
    start = datetime(2026, 1, 7, 9, 0)

    invoice = billing.build_invoice(
        tariff, "THUE-ANPHAT", start, start + timedelta(hours=2),
        previous_kwh=500.0, current_kwh=570.0, service_rate_per_kwh=3500,
        equipment_id=probe.id, rated_power_kw=40.0, source="MODBUS",
    )
    tariff.commit()
    assert invoice["breakdown"]["split_method"] == "telemetry"
    assert invoice["total_kwh"] == pytest.approx(70.0)
    assert sum(invoice["kwh_by_band"].values()) == pytest.approx(70.0, abs=0.5)


# --------------------------------------------------------------------------- #
# Load shifting - con so that tu bieu gia, khong hardcode 35%
# --------------------------------------------------------------------------- #
def test_load_shift_tinh_tu_chenh_lech_gia_that() -> None:
    prices = {TariffBandCode.PEAK.value: 4586, TariffBandCode.NORMAL.value: 2824, TariffBandCode.OFF_PEAK.value: 1808}
    split = {TariffBandCode.PEAK.value: 1000.0, TariffBandCode.NORMAL.value: 2000.0, TariffBandCode.OFF_PEAK.value: 500.0}

    result = billing.load_shift_analysis(split, prices, shift_pct=0.2)
    assert result["shifted_kwh"] == pytest.approx(200.0)
    assert result["price_gap_vnd_per_kwh"] == 4586 - 1808
    assert result["saving_vnd"] == int(round(200.0 * (4586 - 1808)))
    baseline = 1000 * 4586 + 2000 * 2824 + 500 * 1808
    assert result["baseline_electricity_vnd"] == baseline
    assert result["saving_pct"] == pytest.approx(result["saving_vnd"] / baseline * 100, abs=0.01)


def test_load_shift_khong_vuot_100_phu_tai_cao_diem() -> None:
    prices = {TariffBandCode.PEAK.value: 4586, TariffBandCode.NORMAL.value: 2824, TariffBandCode.OFF_PEAK.value: 1808}
    split = {TariffBandCode.PEAK.value: 100.0, TariffBandCode.NORMAL.value: 0.0, TariffBandCode.OFF_PEAK.value: 0.0}
    assert billing.load_shift_analysis(split, prices, shift_pct=5.0)["shifted_kwh"] == pytest.approx(100.0)
    assert billing.load_shift_analysis(split, prices, shift_pct=-1.0)["shifted_kwh"] == 0.0


def test_load_shift_khong_co_cao_diem_thi_khong_tiet_kiem() -> None:
    prices = {TariffBandCode.PEAK.value: 4586, TariffBandCode.NORMAL.value: 2824, TariffBandCode.OFF_PEAK.value: 1808}
    split = {TariffBandCode.PEAK.value: 0.0, TariffBandCode.NORMAL.value: 500.0, TariffBandCode.OFF_PEAK.value: 500.0}
    result = billing.load_shift_analysis(split, prices)
    assert result["saving_vnd"] == 0
    assert result["saving_pct"] == 0.0
