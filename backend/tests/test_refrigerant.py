"""Tinh chat nhiet vat ly moi chat lanh: moi so lieu phai den tu CoolProp, khong go tay.

Bo test nay giu ba dieu khong duoc vo:

  1. HAI BANG MOI CHAT KHONG DUOC LECH NHAU. `COOLPROP_FLUIDS` (refrigerant.py) va
     `GWP_FACTORS` (compliance.py) cung khoa bo nhan moi chat. Lech nhau thi mot thiet bi
     tinh duoc COP Carnot nhung khong tinh duoc Scope 1, hoac nguoc lai - ca hai deu la
     bao cao khuyet ma khong ai thay.

  2. KHONG DUOC DOAN. Nhan la thi phai bao loi, thieu du lieu thi phai tra ve None.
     Tra ve mot gia tri mac dinh o day la chep mot con so bia vao bao cao co ky.

  3. DU LIEU SEED PHAI NHAT QUAN VE NHET DONG HOC. Ap suat trong telemetry phai ung voi
     nhiet do bay hoi thap hon nhiet do dat cua kho. Neu khong, moi chan doan suy ra tu
     ap suat deu dang doc mot he thong vat ly khong ton tai.
"""

from __future__ import annotations

import pytest
from CoolProp.CoolProp import PropsSI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import REFRIGERATION_KINDS, Equipment, TelemetrySample
from app.services.compliance import GWP_FACTORS
from app.services.refrigerant import (
    COOLPROP_FLUIDS,
    RefrigerantError,
    carnot_cop,
    critical_temperature_c,
    known_refrigerants,
    resolve_fluid,
    saturation_pressure_bar,
    saturation_temperature_c,
    second_law_efficiency,
)


# --------------------------------------------------------------------------- #
# 1. Hai bang moi chat phai khoa lan nhau
# --------------------------------------------------------------------------- #
def test_khoa_coolprop_trung_voi_bang_gwp_cua_compliance():
    """Hai bang o hai module khac nhau, khong co rang buoc nao ngoai test nay.

    Them mot moi chat vao seed ma quen cap nhat mot trong hai bang thi loi chi lo ra khi
    khach hang hoi mot cau ma he thong khong tra loi duoc.
    """
    assert set(COOLPROP_FLUIDS) == set(GWP_FACTORS)


def test_moi_nhan_moi_chat_deu_giai_duoc_sang_fluid_that():
    """Mot nhan trung ten trong DB nhung CoolProp khong biet se chi no ra luc chay.

    Goi PropsSI that cho tung nhan: day la test dau tien bat duoc ten fluid go sai.
    """
    for label, fluid in COOLPROP_FLUIDS.items():
        assert resolve_fluid(label) == fluid
        assert PropsSI("Tcrit", fluid) > 0, f"{label} -> {fluid} khong lay duoc Tcrit"


def test_moi_thiet_bi_lanh_trong_seed_deu_co_moi_chat_giai_duoc(seeded: Session):
    """Seed la nguon nhan moi chat duy nhat. Mot nhan la o day lam thiet bi roi khoi
    toan bo chan doan nhiet ma khong bao gio bao loi."""
    equipments = list(seeded.scalars(select(Equipment)))
    refrigeration = [e for e in equipments if e.is_refrigeration]
    assert refrigeration, "Seed khong co thiet bi lanh nao - test nay khong con y nghia"

    for e in refrigeration:
        assert e.refrigerant in COOLPROP_FLUIDS, (
            f"{e.code} khai moi chat '{e.refrigerant}' khong co trong COOLPROP_FLUIDS "
            f"({', '.join(known_refrigerants())})"
        )

    # Thiet bi khong phai lanh (lo hoi) duoc phep khong co moi chat.
    non_refrigeration = [e for e in equipments if not e.is_refrigeration]
    assert any(e.refrigerant is None for e in non_refrigeration)


# --------------------------------------------------------------------------- #
# 2. Khong duoc doan
# --------------------------------------------------------------------------- #
def test_nhan_moi_chat_la_thi_bao_loi_thay_vi_doan():
    with pytest.raises(RefrigerantError) as exc:
        resolve_fluid("R999")
    # Loi phai liet ke cac ma hop le de nguoi van hanh biet sua o dau.
    assert "R999" in str(exc.value)
    for label in known_refrigerants():
        assert label in str(exc.value)


@pytest.mark.parametrize("label", ["R404a", "r404A", " R404A", "404A"])
def test_nhan_sai_chinh_ta_khong_duoc_am_tham_chap_nhan(label: str):
    """Nhan moi chat la chuoi tu do trong DB. Neu 'R404a' duoc am thang coi la R404A thi
    mot loi go chu se thanh mot chan doan sai ma khong ai phat hien."""
    with pytest.raises(RefrigerantError):
        resolve_fluid(label)


def test_thiet_bi_khong_phai_lanh_tra_ve_none_khong_bao_loi():
    """Lo hoi co `refrigerant` NULL. Do khong phai loi: bao loi o day se chan moi phep
    tinh toan tren toan bo danh sach thiet bi."""
    assert resolve_fluid(None) is None
    assert saturation_temperature_c(None, 5.0) is None
    assert saturation_pressure_bar(None, -25.0) is None
    assert critical_temperature_c(None) is None


def test_thieu_so_lieu_thi_tra_ve_none_khong_phai_tra_ve_so_mac_dinh():
    assert saturation_temperature_c("R404A", None) is None
    assert saturation_pressure_bar("R404A", None) is None
    assert carnot_cop(None, 40.0) is None
    assert carnot_cop(-30.0, None) is None
    assert second_law_efficiency(None, 3.0) is None
    assert second_law_efficiency(2.5, None) is None


@pytest.mark.parametrize("pressure", [0.0, -1.0, -0.5])
def test_ap_suat_khong_duong_bao_loi_ro_rang(pressure: float):
    """Ap suat am la cam bien hong hoac du lieu dau vao sai. CoolProp bao loi kieu
    "molar density of -5.2e9 mol/m3" - vo nghia voi nguoi van hanh, nen phai dich lai."""
    with pytest.raises(RefrigerantError) as exc:
        saturation_temperature_c("R404A", pressure)
    assert "0 bar" in str(exc.value)


def test_ap_suat_vuot_toi_han_bao_loi_thay_vi_tra_ve_so_vo_nghia():
    """Tren nhiet do toi han khong con qua trinh ngung tu, nen 'nhiet do bao hoa' khong
    ton tai. Tra ve mot con so o day la chep mot dai luong khong co that vao bao cao."""
    tcrit = critical_temperature_c("R404A")
    assert tcrit is not None
    # Ap suat cao den muc chac chan vuot diem toi han cua R404A.
    with pytest.raises(RefrigerantError):
        saturation_temperature_c("R404A", tcrit * 100)


def test_nhiet_do_duoi_diem_ba_bao_loi():
    with pytest.raises(RefrigerantError):
        saturation_pressure_bar("R404A", -200.0)


# --------------------------------------------------------------------------- #
# 3. Tinh chat vat ly
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label", known_refrigerants())
@pytest.mark.parametrize("temperature_c", [-35.0, -25.0, 0.0, 20.0])
def test_hai_ham_nguoc_phai_khop_nhau(label: str, temperature_c: float):
    """T -> P -> T phai tra ve dung gia tri ban dau.

    Day la test bat loi quy uoc (bubble vs dew) hieu qua nhat: neu hai ham lay hai diem
    khac nhau thi vong lap nay lech ngay. R404A la hon hop zeotropic nen truot nhiet do
    ~0.65 K - lech khoang do la dau hieu hai ham khong dung chung mot quy uoc.
    """
    pressure = saturation_pressure_bar(label, temperature_c)
    assert pressure is not None and pressure > 0
    back = saturation_temperature_c(label, pressure)
    assert back == pytest.approx(temperature_c, abs=1e-6)


@pytest.mark.parametrize("label", known_refrigerants())
def test_ap_suat_bao_hoa_tang_theo_nhiet_do(label: str):
    """Quan he don dieu nay la nen cua moi bang P-T. Dao chieu la dau hieu mot loi
    trong cach doi don vi hoac trong quy uoc chat long/hoi."""
    colder = saturation_pressure_bar(label, -30.0)
    warmer = saturation_pressure_bar(label, 10.0)
    assert colder is not None and warmer is not None
    assert warmer > colder


@pytest.mark.parametrize("label", known_refrigerants())
def test_nhiet_do_toi_han_nam_trong_mien_hop_ly(label: str):
    """Chan loi doi don vi: quen tru 273.15 se tra ve Kelvin (vi du 345 thay vi 72)."""
    tcrit = critical_temperature_c(label)
    assert tcrit is not None
    assert 40.0 < tcrit < 200.0


def test_cop_carnot_khop_voi_cong_thuc_tinh_bang_tay():
    """COP_carnot = T_evap / (T_cond - T_evap) theo Kelvin.

    Con so ky vong o day tinh tay duoc: day la cong thuc cua chinh module nay, khong phai
    du lieu cua CoolProp, nen tinh tay khong vi pham quy tac "khong go tay so lieu".
    """
    # -30 C = 243.15 K, 40 C = 313.15 K -> 243.15 / 70 = 3.4735714...
    assert carnot_cop(-30.0, 40.0) == 3.474
    # 0 C = 273.15 K, 40 C = 313.15 K -> 273.15 / 40 = 6.82875
    assert carnot_cop(0.0, 40.0) == 6.829


def test_tran_vat_ly_thap_hon_khi_choi_am_sau_hon():
    """Ly do ton tai cua ham carnot_cop.

    Kho -35 C giai nhiet ra 40 C co tran COP thap hon kho +2 C giai nhiet ra 35 C, du
    ca hai cung la 'may lanh'. Vi vay so sanh COP thoi giua hai kho la vo nghia - phai
    so sanh theo hieu suat luat hai. Day la dieu ma mot nguong COP hardcode khong thay.
    """
    deep_freezer = carnot_cop(-35.0, 40.0)
    cold_room = carnot_cop(2.0, 35.0)
    assert deep_freezer is not None and cold_room is not None
    assert deep_freezer < cold_room


def test_cop_carnot_tang_khi_chenh_lech_nhiet_do_hep_lai():
    """Cung T_evap nhung dan nong mat hon thi tran cao hon. Day la co so vat ly cua
    khuyen nghi 've sinh dan nong' - khuyen nghi do phai co tran nay chung minh."""
    hot_condenser = carnot_cop(-25.0, 50.0)
    clean_condenser = carnot_cop(-25.0, 38.0)
    assert hot_condenser is not None and clean_condenser is not None
    assert clean_condenser > hot_condenser


def test_t_cond_thap_hon_t_evap_la_du_lieu_sai_chu_khong_phai_trang_thai_that():
    """Nhiet khong tu chay tu noi lanh sang noi nong. Tra ve COP am o day se lot xuong
    bao cao thanh mot con so co dau tru ma khong ai hieu."""
    with pytest.raises(RefrigerantError) as exc:
        carnot_cop(-10.0, -20.0)
    assert "T_cond" in str(exc.value)

    with pytest.raises(RefrigerantError):
        carnot_cop(-10.0, -10.0)


def test_hieu_suat_luat_hai_nam_trong_0_den_1_voi_thiet_bi_that():
    """May that khong the vuot tran Carnot. Neu con so nay > 1 thi hoac COP do duoc sai,
    hoac T_evap/T_cond suy ra tu ap suat sai - ca hai deu la loi can bi bat."""
    carnot = carnot_cop(-25.0, 40.0)
    assert carnot is not None
    for measured_cop in (1.0, 1.8, 2.5):
        ratio = second_law_efficiency(measured_cop, carnot)
        assert ratio is not None
        assert 0.0 < ratio < 1.0


def test_hieu_suat_luat_hai_bac_cop_vuot_tran_vat_ly():
    """Chan du lieu bat thuong: COP do duoc vuot tran Carnot nghia la mot trong cac dau
    vao sai. Chan doan phai nhin thay truong hop nay thay vi keo no vao xu ly binh thuong."""
    carnot = carnot_cop(-25.0, 40.0)
    assert carnot is not None
    impossible = second_law_efficiency(carnot * 2, carnot)
    assert impossible is not None and impossible > 1.0


# --------------------------------------------------------------------------- #
# 4. Du lieu seed phai nhat quan ve nhiet dong hoc
# --------------------------------------------------------------------------- #
#: Chenh lech nhiet do cho phep giua nhiet do bay hoi va nhiet do dat cua kho.
#: Duoi 3 K thi dan bay hoi phai lon vo ly; tren 15 K la may dang chay rat kem hieu qua
#: (hoac dang dong bang nang). Mien nay la kien thuc nganh, khong phai so lieu moi chat,
#: nen nam o test thay vi nam trong module tinh toan.
MIN_EVAP_APPROACH_K = 3.0
MAX_EVAP_APPROACH_K = 15.0


def test_ap_suat_seed_ung_voi_nhiet_do_bay_hoi_hop_ly(seeded: Session):
    """Ap suat trong telemetry phai suy ra duoc mot nhiet do bay hoi NAM DUOI nhiet do
    dat cua kho (nhiet tu chay tu kho sang moi chat), voi chenh lech trong mien hop ly.

    Test nay bat duoc mot lop loi ma khong test don vi nao bat duoc: moi hang so sinh du
    lieu deu "trong co ve hop ly", nhung khop lai voi phuong trinh trang thai cua moi chat
    thi khong. Chan doan suy ra T_evap tu chinh ap suat nay, nen seed lech thi chan doan
    se ket luan sai tren mot he thong khong ton tai.
    """
    violations: list[str] = []

    # `is_refrigeration` la property Python nen khong dung duoc trong .where(); loc theo
    # REFRIGERATION_KINDS - cung mot nguon ma property do doc, nen khong the lech nhau.
    refrigeration_kinds = [kind.value for kind in REFRIGERATION_KINDS]
    equipments = list(
        seeded.scalars(select(Equipment).where(Equipment.kind.in_(refrigeration_kinds)))
    )
    assert equipments, "Seed khong co thiet bi lanh nao - test nay khong con y nghia"

    for equipment in equipments:
        if equipment.refrigerant is None or equipment.setpoint_c is None:
            continue

        expected_evap_c = equipment.setpoint_c - (MIN_EVAP_APPROACH_K + MAX_EVAP_APPROACH_K) / 2
        expected_bar = saturation_pressure_bar(equipment.refrigerant, expected_evap_c)
        assert expected_bar is not None

        # Khoang ap suat tuong ung voi toan bo mien chenh lech cho phep.
        low = saturation_pressure_bar(equipment.refrigerant, equipment.setpoint_c - MAX_EVAP_APPROACH_K)
        high = saturation_pressure_bar(equipment.refrigerant, equipment.setpoint_c - MIN_EVAP_APPROACH_K)
        assert low is not None and high is not None

        samples = list(
            seeded.scalars(
                select(TelemetrySample)
                .where(TelemetrySample.equipment_id == equipment.id)
                .limit(200)
            )
        )
        for sample in samples:
            if sample.pressure_bar is None:
                continue
            evap_c = saturation_temperature_c(equipment.refrigerant, sample.pressure_bar)
            if evap_c is None:
                continue
            approach = equipment.setpoint_c - evap_c
            if not (MIN_EVAP_APPROACH_K <= approach <= MAX_EVAP_APPROACH_K):
                violations.append(
                    f"{equipment.code} ({equipment.refrigerant}, setpoint {equipment.setpoint_c} C): "
                    f"P={sample.pressure_bar} bar -> T_evap={evap_c:.2f} C, "
                    f"chenh lech {approach:.2f} K nam ngoai mien "
                    f"[{MIN_EVAP_APPROACH_K}, {MAX_EVAP_APPROACH_K}]; "
                    f"mien hop ly la {low:.2f}-{high:.2f} bar"
                )

    assert not violations, (
        "Telemetry seed khong nhat quan ve nhiet dong hoc:\n  " + "\n  ".join(violations[:20])
    )
