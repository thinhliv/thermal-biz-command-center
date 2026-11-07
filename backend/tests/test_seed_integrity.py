"""Du lieu seed la thu nguoi dung thay dau tien khi chay demo.

Nhung bat bien o day ma hong thi UI "chay duoc" nhung hien so sai: COP lan voi hieu suat
lo hoi, bieu gia EVN thieu khung gio, hoa don khong khop tong, canh bao mo khong co thiet bi.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    AlarmRule,
    BilledInvoice,
    Customer,
    Equipment,
    EquipmentKind,
    MeterReading,
    MonthlyTarget,
    Receivable,
    ReceivableStatus,
    ServiceOrder,
    TariffBand,
    TariffBandCode,
    TelemetrySample,
    User,
)
from app.seed import DEMO_USERS, EVN_PRICES, RANDOM_SEED, reset, seed_if_empty
from app.security import verify_password


@pytest.fixture()
def stats(seeded: Session) -> dict:
    return seed_if_empty(seeded, force=False)


def test_seed_tra_ve_thong_ke_day_du(seeded: Session, stats: dict):
    """Goi lan 2 tren DB da co du lieu -> khong seed lai, khong nhan doi ban ghi."""
    assert stats == {"seeded": False, "reason": "Da co du lieu, bo qua seed."}


def test_seed_xac_dinh_duoc_lap_lai(session: Session):
    """RANDOM_SEED co dinh -> hai lan seed cho cung mot bo du lieu (demo khong doi moi lan chay)."""
    first = seed_if_empty(session, force=True)
    counts = {k: v for k, v in first.items() if isinstance(v, int)}
    reset(session)
    session.commit()

    second = seed_if_empty(session, force=True)
    assert {k: v for k, v in second.items() if isinstance(v, int)} == counts
    assert counts["telemetry_samples"] > 0


def test_seed_tao_du_cac_bang_nghiep_vu(seeded: Session):
    for model, minimum in [
        (User, 3),
        (TariffBand, 8),
        (Equipment, 8),
        (AlarmRule, 5),
        (TelemetrySample, 100),
        (Customer, 3),
        (ServiceOrder, 10),
        (Receivable, 5),
        (BilledInvoice, 1),
        (Alert, 1),
    ]:
        count = len(list(seeded.scalars(select(model))))
        assert count >= minimum, f"{model.__tablename__} chi co {count} ban ghi, can >= {minimum}"


# --------------------------------------------------------------------------- #
# Nguoi dung
# --------------------------------------------------------------------------- #
def test_co_du_3_vai_tro(seeded: Session):
    users = {u.username: u for u in seeded.scalars(select(User))}
    assert {u.role for u in users.values()} == {role.value for _, role, _, _ in DEMO_USERS}
    assert set(users) == {username for username, _, _, _ in DEMO_USERS}


def test_mat_khau_duoc_bam_khong_luu_plaintext(seeded: Session):
    from app.config import get_settings

    password = get_settings().seed_demo_user_password
    for user in seeded.scalars(select(User)):
        assert user.password_hash != password
        assert user.password_hash.startswith("$2")  # bcrypt
        assert verify_password(password, user.password_hash) is True
        assert verify_password("sai-mat-khau", user.password_hash) is False


# --------------------------------------------------------------------------- #
# Thiet bi: COP va eta khong lan lon
# --------------------------------------------------------------------------- #
def test_moi_thiet_bi_deu_co_kind_hop_le(seeded: Session):
    for item in seeded.scalars(select(Equipment)):
        assert EquipmentKind(item.kind) in set(EquipmentKind)


def test_lo_hoi_chi_co_hieu_suat_thiet_bi_lanh_chi_co_cop(seeded: Session):
    boilers = refrigeration = 0
    for item in seeded.scalars(select(Equipment)):
        if item.is_combustion:
            boilers += 1
            assert item.design_cop is None, f"{item.code} la lo hoi nhung lai co COP"
            assert item.design_efficiency_pct is not None
            assert 0 < item.design_efficiency_pct <= 100
        else:
            refrigeration += 1
            assert item.design_efficiency_pct is None, f"{item.code} la thiet bi lanh nhung lai co eta"
            assert item.design_cop is not None
            # COP may lanh thuong 2.5-5; ngoai khoang nay la seed sai don vi
            assert 1.5 <= item.design_cop <= 6.5, f"{item.code} COP thiet ke {item.design_cop} bat thuong"

    assert boilers >= 1 and refrigeration >= 5


def test_thiet_bi_cho_thue_co_du_thong_tin_de_xuat_hoa_don(seeded: Session):
    """Thieu tenant_code hoac meter_entity_id thi billing connector B khong chay duoc."""
    tenants = list(seeded.scalars(select(Equipment).where(Equipment.tenant_code.is_not(None))))
    assert len(tenants) >= 2

    for item in tenants:
        assert item.meter_entity_id, f"{item.code} co tenant nhung thieu cong to"
        assert "." in item.meter_entity_id
        assert item.rated_power_kw and item.rated_power_kw > 0
        assert item.is_active is True

    assert len({t.tenant_code for t in tenants}) == len(tenants), "Hai thiet bi dung chung mot tenant"


def test_kho_lanh_hai_san_co_nguong_haccp(seeded: Session):
    from app.services.thermal import HACCP_SEAFOOD_LIMIT_C

    freezers = list(
        seeded.scalars(
            select(Equipment).where(Equipment.kind.in_([EquipmentKind.DEEP_FREEZER.value, EquipmentKind.BLAST_FREEZER.value]))
        )
    )
    assert freezers, "Seed phai co it nhat mot kho dong / ham cap dong"
    for item in freezers:
        assert item.haccp_limit_c == HACCP_SEAFOOD_LIMIT_C
        assert item.refrigerant, f"{item.code} thieu loai gas lanh"


# --------------------------------------------------------------------------- #
# Telemetry
# --------------------------------------------------------------------------- #
def test_mau_telemetry_khong_lan_cop_voi_hieu_suat(seeded: Session):
    equipment = {e.id: e for e in seeded.scalars(select(Equipment))}
    for sample in seeded.scalars(select(TelemetrySample)):
        item = equipment[sample.equipment_id]
        if item.is_combustion:
            assert sample.cop is None, f"{item.code}: lo hoi khong duoc co COP trong telemetry"
        else:
            assert sample.efficiency_pct is None, f"{item.code}: thiet bi lanh khong duoc co eta"
            if sample.cop is not None:
                assert 0.5 <= sample.cop <= 8.0


def test_cop_trong_seed_khop_cong_thuc_qo_chia_ne(seeded: Session):
    """COP luon duoc tinh lai tu Q_o va N_e - ke ca trong du lieu mau."""
    checked = 0
    for sample in seeded.scalars(select(TelemetrySample)):
        if sample.cop is None or not sample.power_kw or not sample.cooling_capacity_kw:
            continue
        checked += 1
        assert abs(sample.cop - sample.cooling_capacity_kw / sample.power_kw) < 0.01
    assert checked > 50, f"Chi co {checked} mau du Q_o va N_e de doi chieu"


def test_mau_telemetry_khong_vuong_o_tuong_lai(seeded: Session):
    from app.timeutil import utcnow

    now = utcnow()
    for sample in seeded.scalars(select(TelemetrySample)):
        assert sample.ts <= now, "Telemetry mau o tuong lai se lam loan 'su co dang dien ra'"


def test_khong_co_mau_telemetry_trung_thoi_diem(seeded: Session):
    keys = [(s.equipment_id, s.ts) for s in seeded.scalars(select(TelemetrySample))]
    assert len(keys) == len(set(keys))


# --------------------------------------------------------------------------- #
# Bieu gia EVN
# --------------------------------------------------------------------------- #
def test_bieu_gia_khop_bang_gia_evn(seeded: Session):
    prices = {b.code: b.price_vnd_per_kwh for b in seeded.scalars(select(TariffBand))}
    assert prices == {code.value: value for code, value in EVN_PRICES.items()}


def test_bieu_gia_co_hieu_luc_tu_ngay_hop_le(seeded: Session):
    today = date.today()
    for band in seeded.scalars(select(TariffBand)):
        assert band.is_active is True
        assert band.effective_from <= today, "Bieu gia chua co hieu luc -> billing se bao 503"


def test_bieu_gio_phu_kin_24h_khong_chong_lap(seeded: Session):
    """Voi moi thu trong tuan, tong so phut cac khung gio phai dung 1440 va khong de giay nao lo gia."""
    bands = list(seeded.scalars(select(TariffBand)))
    for weekday in range(1, 8):  # ISO: 1=thu Hai .. 7=Chu nhat
        applicable = [b for b in bands if b.days == "*" or str(weekday) in {d.strip() for d in b.days.split(",")}]
        covered = sorted((b.start_minute, b.end_minute) for b in applicable)

        total = 0
        cursor = 0
        for start, end in covered:
            assert start == cursor, f"Thu {weekday}: lo khoang {cursor}-{start} phut khong thuoc khung gio nao"
            total += end - start
            cursor = end
        assert total == 1440, f"Thu {weekday} chi phu {total}/1440 phut"


def test_khung_gio_nam_tron_ve_truoc_sau_ranh_mach(seeded: Session):
    for band in seeded.scalars(select(TariffBand)):
        assert 0 <= band.start_minute < band.end_minute <= 1440
        assert band.name_vn


# --------------------------------------------------------------------------- #
# Kinh doanh
# --------------------------------------------------------------------------- #
def test_tong_hoa_don_bang_tien_dien_cong_phi_quan_ly(seeded: Session):
    invoices = list(seeded.scalars(select(BilledInvoice)))
    for inv in invoices:
        assert inv.total_vnd == inv.electricity_vnd + inv.service_fee_vnd, f"Hoa don {inv.id} lech tong"
        assert inv.total_kwh > 0
        assert inv.electricity_vnd > 0
        assert abs(inv.total_kwh - (inv.peak_kwh + inv.normal_kwh + inv.off_peak_kwh)) < 0.5
        assert inv.period_end > inv.period_start


def test_hoa_don_khong_trung_ky(seeded: Session):
    periods = [
        (i.tenant_code, i.period_start, i.period_end) for i in seeded.scalars(select(BilledInvoice))
    ]
    assert len(periods) == len(set(periods)), "Idempotency hong: hai hoa don cung tenant cung ky"


def test_moi_hoa_don_deu_co_lan_doc_cong_to_tuong_ung(seeded: Session):
    readings = {r.id for r in seeded.scalars(select(MeterReading))}
    linked = 0
    for inv in seeded.scalars(select(BilledInvoice)):
        if inv.meter_reading_id is not None:
            linked += 1
            assert inv.meter_reading_id in readings
    assert linked > 0, "Hoa don phai truy vet duoc ve chi so cong to"


def test_delta_kwh_cua_lan_doc_khong_am_va_khop_chi_so(seeded: Session):
    for reading in seeded.scalars(select(MeterReading)):
        assert reading.delta_kwh >= 0
        assert reading.period_end > reading.period_start
        if reading.reading_start_kwh is not None:
            assert reading.delta_kwh == pytest.approx(reading.reading_end_kwh - reading.reading_start_kwh, abs=0.5)


def test_cong_no_khong_luu_trang_thai_qua_han(seeded: Session):
    """OVERDUE phai suy ra tu due_at vs hom nay, khong duoc dong bang thanh status."""
    valid = {s.value for s in ReceivableStatus}
    for item in seeded.scalars(select(Receivable)):
        assert item.status in valid
        assert item.status != "OVERDUE"
        assert item.amount_vnd >= item.paid_amount_vnd >= 0


def test_don_hang_gan_voi_khach_hang_va_thiet_bi_co_that(seeded: Session):
    customers = {c.id for c in seeded.scalars(select(Customer))}
    equipment = {e.id for e in seeded.scalars(select(Equipment))}
    for order in seeded.scalars(select(ServiceOrder)):
        assert order.customer_id in customers
        if order.equipment_id is not None:
            assert order.equipment_id in equipment


def test_muc_tieu_thang_hop_le(seeded: Session):
    for target in seeded.scalars(select(MonthlyTarget)):
        assert 1 <= target.month <= 12


# --------------------------------------------------------------------------- #
# Canh bao
# --------------------------------------------------------------------------- #
def test_rule_canh_bao_bam_vao_metric_co_that(seeded: Session):
    valid_metrics = {c.name for c in TelemetrySample.__table__.columns}
    for rule in seeded.scalars(select(AlarmRule)):
        assert rule.metric in valid_metrics, f"Rule bam vao cot khong ton tai: {rule.metric}"
        assert rule.duration_minutes >= 0


def test_canh_bao_mo_deu_truy_vet_duoc(seeded: Session):
    equipment = {e.id for e in seeded.scalars(select(Equipment))}
    open_alerts = [a for a in seeded.scalars(select(Alert)) if a.cleared_at is None]
    assert open_alerts, "Seed phai tao it nhat mot canh bao dang mo de demo tab Canh bao"
    for alert in open_alerts:
        assert alert.equipment_id in equipment
        assert alert.severity in {"CRITICAL", "MAJOR", "WARNING", "INFO"}
        assert alert.message.strip()


def test_canh_bao_duoc_sinh_ra_tu_telemetry_that(seeded: Session):
    """Khong phai alert 'viet tay': phai co mau vi pham nguong that su."""
    samples = list(seeded.scalars(select(TelemetrySample)))
    raised = [a for a in seeded.scalars(select(Alert)) if a.metric is not None and a.observed_value is not None]
    assert raised

    rules = {r.id: r for r in seeded.scalars(select(AlarmRule))}
    for alert in raised:
        rule = rules.get(alert.rule_id)
        if rule is None:
            continue
        matching = [
            s
            for s in samples
            if s.equipment_id == alert.equipment_id and rule.is_breached(getattr(s, alert.metric, None))
        ]
        assert matching, f"Alert {alert.id} bao vi pham {alert.metric} nhung telemetry khong co mau nao vi pham"


def test_reset_xoa_het_du_lieu_nghiep_vu(seeded: Session):
    reset(seeded)
    seeded.commit()

    assert seeded.scalars(select(Equipment).limit(1)).first() is None
    assert seeded.scalars(select(TelemetrySample).limit(1)).first() is None
    assert seeded.scalars(select(BilledInvoice).limit(1)).first() is None
    # Seed lai duoc sau khi reset
    assert seed_if_empty(seeded, force=False)["seeded"] is True


def test_random_seed_duoc_co_dinh():
    assert RANDOM_SEED == 20260107
