"""Ky thuat nhiet lanh: COP khong duoc lan lon voi hieu suat lo hoi, HACCP, ISO 10816,
va co che canh bao co `duration_minutes` (chong nhieu nhay)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AlarmRule,
    Comparator,
    Equipment,
    EquipmentKind,
    Metric,
    Severity,
    TelemetrySample,
)
from app.services import thermal
from app.services.thermal import (
    HACCP_SEAFOOD_LIMIT_C,
    VIBRATION_ISO10816_LIMIT_MM_S,
    assess_health,
    compute_cop,
    evaluate_sample,
    rules_for,
    summarize_thermal,
)

T0 = datetime(2026, 3, 4, 8, 0)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def _freezer(session: Session, code: str = "KHO_DONG_T", **kw) -> Equipment:
    fields = {
        "code": code,
        "name": f"Kho dong {code}",
        "kind": EquipmentKind.DEEP_FREEZER.value,
        "rated_power_kw": 45.0,
        "setpoint_c": -25.0,
        "haccp_limit_c": HACCP_SEAFOOD_LIMIT_C,
        "design_cop": 3.8,
        "is_active": True,
    }
    fields.update(kw)
    item = Equipment(**fields)
    session.add(item)
    session.flush()
    return item


def _boiler(session: Session, code: str = "LO_HOI_T", **kw) -> Equipment:
    fields = {
        "code": code,
        "name": f"Lo hoi {code}",
        "kind": EquipmentKind.BOILER.value,
        "rated_power_kw": 48.0,
        "design_efficiency_pct": 85.0,
        "is_active": True,
    }
    fields.update(kw)
    item = Equipment(**fields)
    session.add(item)
    session.flush()
    return item


def _sample(session: Session, equipment: Equipment, ts: datetime, **kw) -> TelemetrySample:
    row = TelemetrySample(equipment_id=equipment.id, ts=ts, **kw)
    session.add(row)
    session.flush()
    return row


def _rule(session: Session, **kw) -> AlarmRule:
    fields = {
        "metric": Metric.TEMPERATURE_C.value,
        "comparator": Comparator.GT.value,
        "threshold": -18.0,
        "duration_minutes": 0,
        "severity": Severity.WARNING.value,
        "message_template": "",
        "is_haccp": False,
        "enabled": True,
    }
    fields.update(kw)
    rule = AlarmRule(**fields)
    session.add(rule)
    session.flush()
    return rule


# --------------------------------------------------------------------------- #
# COP = Q_o / N_e
# --------------------------------------------------------------------------- #
def test_cop_la_thuong_cua_cong_suat_lanh_va_dien():
    assert compute_cop(152.0, 40.0) == 3.8


def test_cop_bang_none_khi_may_dung_hoac_thieu_du_lieu():
    """N_e <= 0 la may dung (hoac cam bien hong) -> khong duoc bao cao COP 0 hay vo cuc."""
    assert compute_cop(152.0, 0.0) is None
    assert compute_cop(152.0, -3.0) is None
    assert compute_cop(None, 40.0) is None
    assert compute_cop(152.0, None) is None


def test_cop_lam_tron_3_chu_so():
    assert compute_cop(100.0, 30.0) == 3.333


def test_db_chan_lo_hoi_co_cop(session: Session):
    """COP va eta la hai dai luong khac nhau - chan ngay o tang luu tru."""
    session.add(
        Equipment(
            code="LO_SAI",
            name="Lo hoi gan COP sai",
            kind=EquipmentKind.BOILER.value,
            design_efficiency_pct=85.0,
            design_cop=0.9,
        )
    )
    with pytest.raises(IntegrityError, match="ck_boiler_has_no_cop"):
        session.flush()


def test_db_chan_thiet_bi_lanh_co_hieu_suat_dot(session: Session):
    session.add(
        Equipment(
            code="KHO_SAI",
            name="Kho lanh gan hieu suat dot sai",
            kind=EquipmentKind.DEEP_FREEZER.value,
            design_cop=3.8,
            design_efficiency_pct=85.0,
        )
    )
    with pytest.raises(IntegrityError, match="ck_refrigeration_has_no_eta"):
        session.flush()


# --------------------------------------------------------------------------- #
# assess_health
# --------------------------------------------------------------------------- #
def test_assess_health_tinh_cop_gap_cho_thiet_bi_lanh(session: Session):
    kho = _freezer(session, design_cop=4.0)
    sample = _sample(session, kho, T0, temperature_c=-25.0, cop=3.0)

    health = assess_health(kho, sample)

    assert health.is_refrigeration is True
    assert health.is_combustion is False
    # (3.0 - 4.0) / 4.0 = -25%  -> thieu gas lanh hoac dan nong ban
    assert health.cop_gap_pct == -25.0


def test_assess_health_khong_tinh_cop_gap_cho_lo_hoi(session: Session):
    lo = _boiler(session)
    # Gia su mot mau LOI co ca cop lan eta -> van khong duoc suy ra cop_gap cho lo hoi
    sample = _sample(session, lo, T0, cop=0.9, efficiency_pct=78.0)

    health = assess_health(lo, sample)

    assert health.is_combustion is True
    assert health.is_refrigeration is False
    assert health.cop_gap_pct is None
    assert health.efficiency_pct == 78.0


def test_haccp_breach_dung_nguong_toi_da(session: Session):
    """HACCP: nhiet do TAM (toi da) -18C. Dung -18 la dat, nong hon la vi pham."""
    kho = _freezer(session, haccp_limit_c=-18.0)

    assert assess_health(kho, _sample(session, kho, T0, temperature_c=-18.0)).haccp_breach is False
    assert assess_health(kho, _sample(session, kho, T0 + timedelta(minutes=15), temperature_c=-18.1)).haccp_breach is False
    assert assess_health(kho, _sample(session, kho, T0 + timedelta(minutes=30), temperature_c=-17.9)).haccp_breach is True


def test_haccp_khong_ap_dung_khi_thiet_bi_khong_khai_bao_nguong(session: Session):
    kho = _freezer(session, code="KHO_KO_HACCP", haccp_limit_c=None)
    sample = _sample(session, kho, T0, temperature_c=25.0)
    assert assess_health(kho, sample).haccp_breach is False


def test_rung_theo_iso_10816(session: Session):
    """4.5 mm/s la ranh gioi vung C/D: dung 4.5 van dat, vuot moi canh bao."""
    kho = _freezer(session)
    assert VIBRATION_ISO10816_LIMIT_MM_S == 4.5

    assert assess_health(kho, _sample(session, kho, T0, vibration_mm_s=4.5)).vibration_critical is False
    assert assess_health(kho, _sample(session, kho, T0 + timedelta(minutes=15), vibration_mm_s=4.51)).vibration_critical is True
    # Khong co cam bien rung -> khong duoc suy ra "binh thuong" thanh canh bao
    assert assess_health(kho, _sample(session, kho, T0 + timedelta(minutes=30), vibration_mm_s=None)).vibration_critical is False


def test_status_mac_dinh_unknown_khi_mau_khong_khai_bao(session: Session):
    kho = _freezer(session)
    assert assess_health(kho, _sample(session, kho, T0)).status == "UNKNOWN"


# --------------------------------------------------------------------------- #
# AlarmRule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("comparator", "threshold", "value", "expected"),
    [
        ("GT", -18.0, -17.0, True),
        ("GT", -18.0, -18.0, False),
        ("GTE", -18.0, -18.0, True),
        ("LT", 3.0, 2.9, True),
        ("LT", 3.0, 3.0, False),
        ("LTE", 3.0, 3.0, True),
        # COP sut duoi nguong -> canh bao LT
        ("LT", 3.2, 2.8, True),
    ],
)
def test_is_breached_theo_tung_phep_so_sanh(session: Session, comparator, threshold, value, expected):
    rule = _rule(session, comparator=comparator, threshold=threshold)
    assert rule.is_breached(value) is expected


def test_is_breached_false_khi_thieu_gia_tri(session: Session):
    """Cam bien hong (None) khong phai la 'khong vi pham' - nhung cung khong duoc bao dong."""
    rule = _rule(session, comparator="GT", threshold=-18.0)
    assert rule.is_breached(None) is False


def test_render_message_dung_4_bien_cho_phep(session: Session):
    kho = _freezer(session, code="KHO_DONG_01", name="Kho Dong So 1")
    rule = _rule(session, message_template="{code} ({equipment}) nhiet {value}C, nguong {threshold}C")
    assert rule.render_message(kho, -17.2) == "KHO_DONG_01 (Kho Dong So 1) nhiet -17.2C, nguong -18.0C"


def test_rules_for_loc_theo_kind_va_thiet_bi(session: Session):
    kho = _freezer(session, code="KHO_A")
    lo = _boiler(session, code="LO_A")

    _rule(session, applies_to_kind=EquipmentKind.DEEP_FREEZER.value)  # chi kho dong
    _rule(session, metric=Metric.EFFICIENCY_PCT.value, comparator="LT", threshold=80.0,
          applies_to_kind=EquipmentKind.BOILER.value)  # chi lo hoi
    _rule(session, equipment_id=kho.id, metric=Metric.COP.value, comparator="LT", threshold=3.0)
    _rule(session, applies_to_kind=None, equipment_id=None, metric=Metric.POWER_KW.value)  # toan cuc

    assert len(rules_for(session, kho)) == 3  # kind kho dong + rieng kho + toan cuc
    assert len(rules_for(session, lo)) == 2  # kind lo hoi + toan cuc


def test_rules_for_bo_qua_rule_da_tat(session: Session):
    kho = _freezer(session, code="KHO_B")
    _rule(session, enabled=False)
    _rule(session, metric=Metric.VIBRATION_MM_S.value, comparator="GT", threshold=4.5)

    assert len(rules_for(session, kho)) == 1
    assert len(rules_for(session, kho, enabled_only=False)) == 2


# --------------------------------------------------------------------------- #
# evaluate_sample: duration_minutes, vong doi canh bao, chong trung
# --------------------------------------------------------------------------- #
def test_duration_0_bao_ngay_lap_tuc(session: Session):
    kho = _freezer(session, code="KHO_C")
    rule = _rule(session, duration_minutes=0)
    sample = _sample(session, kho, T0, temperature_c=-17.0)

    created = evaluate_sample(session, kho, sample)

    assert len(created) == 1
    assert created[0].rule_id == rule.id
    assert created[0].observed_value == -17.0
    assert created[0].threshold == -18.0
    assert created[0].raised_at == T0
    assert created[0].cleared_at is None


def test_mot_spike_ngan_khong_bao_dong_khi_co_duration(session: Session):
    """Nhieu nhay 1 mau (mo cua kho, pha dong) khong duoc day canh bao len."""
    kho = _freezer(session, code="KHO_D")
    _rule(session, duration_minutes=30)

    _sample(session, kho, T0, temperature_c=-25.0)
    evaluate_sample(session, kho, _sample(session, kho, T0 + timedelta(minutes=15), temperature_c=-17.0))

    assert thermal.open_alerts(session) == []


def test_chi_bao_khi_vi_pham_keo_dai_suot_duration(session: Session):
    kho = _freezer(session, code="KHO_E")
    _rule(session, duration_minutes=30)

    # t0 ok -> 15/30/45 deu nong hon -18C. Cua so 30 phut chi tron ven vi pham o t0+45.
    evaluate_sample(session, kho, _sample(session, kho, T0, temperature_c=-25.0))
    assert thermal.open_alerts(session) == []
    evaluate_sample(session, kho, _sample(session, kho, T0 + timedelta(minutes=15), temperature_c=-17.5))
    assert thermal.open_alerts(session) == []
    evaluate_sample(session, kho, _sample(session, kho, T0 + timedelta(minutes=30), temperature_c=-17.0))
    assert thermal.open_alerts(session) == []

    created = evaluate_sample(session, kho, _sample(session, kho, T0 + timedelta(minutes=45), temperature_c=-16.5))

    assert len(created) == 1
    assert created[0].raised_at == T0 + timedelta(minutes=45)


def test_chua_du_du_lieu_thi_khong_ket_luan_keo_dai(session: Session):
    """Mau dau tien cua thiet bi moi: khong the noi 'keo dai 30 phut' -> im lang."""
    kho = _freezer(session, code="KHO_F")
    _rule(session, duration_minutes=30)

    created = evaluate_sample(session, kho, _sample(session, kho, T0, temperature_c=-15.0))

    assert created == []


def test_khong_tao_alert_trung_khi_mot_canh_bao_van_mo(session: Session):
    kho = _freezer(session, code="KHO_G")
    _rule(session, duration_minutes=0)

    evaluate_sample(session, kho, _sample(session, kho, T0, temperature_c=-17.0))
    evaluate_sample(session, kho, _sample(session, kho, T0 + timedelta(minutes=15), temperature_c=-16.0))
    evaluate_sample(session, kho, _sample(session, kho, T0 + timedelta(minutes=30), temperature_c=-15.0))

    alerts = thermal.open_alerts(session)
    assert len(alerts) == 1
    # Giu gia tri lan dau phat hien, khong cap nhat am tham
    assert alerts[0].observed_value == -17.0


def test_het_vi_pham_thi_dong_canh_bao(session: Session):
    kho = _freezer(session, code="KHO_H")
    _rule(session, duration_minutes=0)

    evaluate_sample(session, kho, _sample(session, kho, T0, temperature_c=-17.0))
    opened = thermal.open_alerts(session)
    assert len(opened) == 1

    recovered_at = T0 + timedelta(minutes=15)
    evaluate_sample(session, kho, _sample(session, kho, recovered_at, temperature_c=-24.0))

    assert thermal.open_alerts(session) == []
    assert opened[0].cleared_at == recovered_at


def test_mat_du_lieu_khong_duoc_dong_canh_bao(session: Session):
    """Hong cam bien khac voi het su co. Mau None phai giu nguyen canh bao dang mo."""
    kho = _freezer(session, code="KHO_I")
    _rule(session, duration_minutes=0)

    evaluate_sample(session, kho, _sample(session, kho, T0, temperature_c=-17.0))
    evaluate_sample(session, kho, _sample(session, kho, T0 + timedelta(minutes=15), temperature_c=None))

    alerts = thermal.open_alerts(session)
    assert len(alerts) == 1
    assert alerts[0].cleared_at is None


def test_vi_pham_lan_hai_sau_khi_hoi_tao_alert_moi(session: Session):
    kho = _freezer(session, code="KHO_K")
    _rule(session, duration_minutes=0)

    evaluate_sample(session, kho, _sample(session, kho, T0, temperature_c=-17.0))
    evaluate_sample(session, kho, _sample(session, kho, T0 + timedelta(minutes=15), temperature_c=-24.0))
    created = evaluate_sample(session, kho, _sample(session, kho, T0 + timedelta(minutes=30), temperature_c=-16.0))

    assert len(created) == 1
    assert len(thermal.open_alerts(session)) == 1


def test_message_fallback_khi_khong_co_template(session: Session):
    kho = _freezer(session, code="KHO_L", name="Kho Lanh L")
    _rule(session, message_template="", metric=Metric.COP.value, comparator="LT", threshold=3.0)

    created = evaluate_sample(session, kho, _sample(session, kho, T0, cop=2.4))

    assert created[0].message == "Kho Lanh L: cop = 2.4"


def test_alert_haccp_duoc_danh_dau_rieng(session: Session):
    kho = _freezer(session, code="KHO_M")
    _rule(session, is_haccp=True, severity=Severity.CRITICAL.value,
          message_template="{code}: nhiet {value}C vuot nguong HACCP {threshold}C")

    created = evaluate_sample(session, kho, _sample(session, kho, T0, temperature_c=-15.0))

    assert created[0].is_haccp is True
    assert created[0].severity == Severity.CRITICAL.value
    assert created[0].message == "KHO_M: nhiet -15.0C vuot nguong HACCP -18.0C"


def test_rule_tat_khong_sinh_alert(session: Session):
    kho = _freezer(session, code="KHO_N")
    _rule(session, enabled=False)
    assert evaluate_sample(session, kho, _sample(session, kho, T0, temperature_c=-10.0)) == []


def test_serialize_alert_co_du_truong_cho_ui(session: Session):
    kho = _freezer(session, code="KHO_O")
    _rule(session, is_haccp=True)
    evaluate_sample(session, kho, _sample(session, kho, T0, temperature_c=-17.0))
    session.commit()

    payload = thermal.serialize_alert(thermal.open_alerts(session)[0])

    assert payload["equipment_code"] == "KHO_O"
    assert payload["metric"] == Metric.TEMPERATURE_C.value
    assert payload["is_haccp"] is True
    assert payload["raised_at"] == T0.isoformat()
    assert payload["cleared_at"] is None
    assert payload["acknowledged_at"] is None
    assert payload["acknowledged_by"] is None
    # WebSocket day dict nay qua json.dumps -> phai serializable bang encoder mac dinh
    json.loads(json.dumps(payload))


# --------------------------------------------------------------------------- #
# summarize_thermal
# --------------------------------------------------------------------------- #
def test_summary_tach_ro_cop_va_hieu_suat_lo_hoi(session: Session):
    """Diem nghiep vu quan trong nhat: COP binh quan khong duoc keo lo hoi vao."""
    kho1 = _freezer(session, code="KHO_01", design_cop=3.8)
    kho2 = _freezer(session, code="KHO_02", design_cop=3.6)
    lo = _boiler(session, code="LO_01", design_efficiency_pct=85.0)

    _sample(session, kho1, T0, temperature_c=-25.0, power_kw=45.0, cooling_capacity_kw=153.0, cop=3.4, status="RUNNING")
    _sample(session, kho2, T0, temperature_c=-22.0, power_kw=38.0, cooling_capacity_kw=136.8, cop=3.6, status="RUNNING")
    # Lo hoi: eta 0.78*100 = 78%. Neu lan lon, avg_cop se tut xuong ~26 (vong cua UI cu).
    _sample(session, lo, T0, power_kw=48.0, efficiency_pct=78.0, status="RUNNING")

    summary = summarize_thermal(session)
    rows = {r["equipment_code"]: r for r in summary["telemetry"]}

    assert summary["avg_cop"] == 3.5  # (3.4 + 3.6) / 2, khong tinh lo hoi
    assert summary["avg_boiler_efficiency_pct"] == 78.0

    assert rows["LO_01"]["cop"] is None
    assert rows["LO_01"]["efficiency_pct"] == 78.0
    assert rows["LO_01"]["design_efficiency_pct"] == 85.0
    assert rows["KHO_01"]["efficiency_pct"] is None
    assert rows["KHO_01"]["cop"] == 3.4
    assert rows["KHO_01"]["cop_gap_pct"] == round((3.4 - 3.8) / 3.8 * 100, 2)


def test_summary_dem_dung_trang_thai_va_cong_suat(session: Session):
    kho = _freezer(session, code="KHO_03")
    lo = _boiler(session, code="LO_02")

    _sample(session, kho, T0, power_kw=45.0, status="RUNNING", temperature_c=-15.0)  # vi pham HACCP
    _sample(session, lo, T0, power_kw=48.0, status="FAULT")

    summary = summarize_thermal(session)

    assert summary["total_power_kw"] == 93.0
    assert summary["total_units"] == 2
    assert summary["running"] == 1
    assert summary["fault"] == 1
    assert summary["warning"] == 1  # kho vi pham HACCP
    assert summary["vibration_limit_mm_s"] == 4.5
    assert summary["haccp_seafood_limit_c"] == HACCP_SEAFOOD_LIMIT_C


def test_summary_bao_no_data_khi_thiet_bi_chua_co_mau(session: Session):
    kho = _freezer(session, code="KHO_04")
    _sample(session, kho, T0, power_kw=45.0, status="RUNNING")
    _freezer(session, code="KHO_05")  # chua co telemetry

    rows = {r["equipment_code"]: r for r in summarize_thermal(session)["telemetry"]}

    assert rows["KHO_05"]["status"] == "NO_DATA"
    assert rows["KHO_05"]["cop"] is None
    assert rows["KHO_05"]["haccp_breach"] is False


def test_summary_chi_tinh_thiet_bi_dang_hoat_dong(session: Session):
    _freezer(session, code="KHO_06")
    _freezer(session, code="KHO_07", is_active=False)

    summary = summarize_thermal(session)

    assert summary["total_units"] == 1
    assert [r["equipment_code"] for r in summary["telemetry"]] == ["KHO_06"]


def test_summary_avg_cop_none_khi_chua_co_du_lieu(session: Session):
    _boiler(session, code="LO_03")
    summary = summarize_thermal(session)
    assert summary["avg_cop"] is None
    assert summary["avg_boiler_efficiency_pct"] is None


def test_latest_sample_lay_mau_moi_nhat_khong_phai_mau_id_lon(session: Session):
    kho = _freezer(session, code="KHO_08")
    _sample(session, kho, T0 + timedelta(hours=2), temperature_c=-25.0)  # ghi sau, ts moi hon
    _sample(session, kho, T0, temperature_c=-10.0)  # ghi truoc nhung ts cu -> day la du lieu tre

    assert thermal.latest_sample(session, kho.id).temperature_c == -25.0


def test_telemetry_series_tra_ve_theo_thu_tu_thoi_gian_tang_dan(session: Session):
    kho = _freezer(session, code="KHO_09")
    now = thermal.utcnow()
    for offset in (0, 30, 15):
        _sample(session, kho, now - timedelta(minutes=offset), temperature_c=-25.0 + offset)

    series = thermal.telemetry_series(session, kho.id, hours=1)

    assert [s.ts for s in series] == sorted(s.ts for s in series)
    assert len(series) == 3


def test_telemetry_series_giu_cac_mau_moi_nhat_khi_vuot_limit(session: Session):
    """Bieu do cat theo `limit` thi phai cat bo phan CU, khong phai phan vua xay ra."""
    kho = _freezer(session, code="KHO_10")
    now = thermal.utcnow()
    for offset in range(10):  # 0..9 phut truoc, offset 0 la moi nhat
        _sample(session, kho, now - timedelta(minutes=offset), temperature_c=float(offset))

    series = thermal.telemetry_series(session, kho.id, hours=1, limit=3)

    assert [s.temperature_c for s in series] == [2.0, 1.0, 0.0]


def test_telemetry_series_bo_qua_mau_ngoai_khung_gio(session: Session):
    kho = _freezer(session, code="KHO_11")
    now = thermal.utcnow()
    _sample(session, kho, now - timedelta(hours=5), temperature_c=-10.0)
    _sample(session, kho, now - timedelta(minutes=5), temperature_c=-25.0)

    series = thermal.telemetry_series(session, kho.id, hours=1)

    assert [s.temperature_c for s in series] == [-25.0]
