"""Chan doan su co phai tach duoc BON nguyen nhan, va phai noi thang khi chua tach duoc.

File nay giu ba bat bien:
  1. KHONG DUOC ket luan khi du lieu khong cho phep. Logic cu trong `ai_energy.py` thay COP thap
     la noi "ro ri moi chat" - ke ca voi lo hoi (thiet bi khong co moi chat lanh de ma ro ri).
     Thieu du lieu phai tra ve INSUFFICIENT_DATA, khong phai mot doan sai.
  2. KHONG DUOC bịa kha nang tach nguyen nhan. Ban dan nong va mon may nen deu nam o phia cao;
     khi chua co nhiet do ngung tu thi ket qua phai mang `ambiguity`, khong phai mot ket luan
     tu tin.
  3. KHONG mot con so ap suat nao duoc go tay trong test. Moi gia tri ap suat o day deu duoc
     tinh tu nhiet do bang chinh `refrigerant.saturation_pressure_bar` (CoolProp). Go tay thi
     test se "pass" voi mot moi chat va am that voi moi chat khac.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import REFRIGERATION_KINDS, Equipment, EquipmentKind, EquipmentStatus
from app.services.diagnostics import (
    APPROACH_LOW_SIDE_FAULT_K,
    MAX_HEALTHY_APPROACH_K,
    MIN_DEFROST_RECOVERY_K,
    MIN_EFFECTIVE_APPROACH_K,
    MIN_POST_DEFROST_SAMPLES,
    NO_REMEDIATION,
    Confidence,
    FaultCode,
    diagnose_low_side,
    separate_frost_from_undercharge,
)
from app.services.refrigerant import RefrigerantError, saturation_pressure_bar

#: Mot kho dong R404A dat -25 C. Moi chenh lech nhiet do duoi day duoc chon tuong doi voi
#: setpoint nay, va ap suat luon duoc TINH ra tu chenh lech do - khong go tay.
SETPOINT_C = -25.0
LABEL = "R404A"


def _pressure_for_approach(approach_k: float, setpoint_c: float = SETPOINT_C, label: str = LABEL) -> float:
    """Ap suat phia thap sao cho chenh lech nhiet do dan bay hoi dung bang `approach_k`."""
    pressure = saturation_pressure_bar(label, setpoint_c - approach_k)
    assert pressure is not None and pressure > 0
    return pressure


def _finding(result, code: FaultCode):
    for finding in result.findings:
        if finding.code == code:
            return finding
    return None


# --------------------------------------------------------------------------- #
# 1. Thieu du lieu -> KHONG duoc doan
# --------------------------------------------------------------------------- #
def test_lo_hoi_khong_bao_ro_ri_moi_chat():
    """Lo hoi khong co moi chat lanh (models.py rang buoc `design_cop IS NULL` voi BOILER).

    Logic cu ap nguong COP len moi thiet bi lanh va noi "ro ri"; voi lo hoi no khong noi duoc vi
    COP None, nhung mot nguoi doc bao cao thay "khong co canh bao" se hieu la lo hoi dang tot.
    O day phai noi ro la KHONG AP DUNG duoc phuong phap nay.
    """
    result = diagnose_low_side(
        refrigerant_label=None,
        setpoint_c=180.0,
        pressure_bar=9.0,
        measured_cop=None,
    )
    assert result.status is FaultCode.INSUFFICIENT_DATA
    assert result.approach_k is None
    assert result.findings == ()


def test_dang_xa_bang_thi_khong_chan_doan():
    """Luc xa bang, dan bay hoi duoc nong hoa khi nen vao nen ap suat phia thap khong on dinh.

    Chan doan trong luc nay se bao dong sai MOT CACH CO HE THONG: cu moi chu ky xa bang lai ra mot
    canh bao thieu gas. `thermal.py` da co co che `duration_minutes` chong nhieu nhay; day la
    lop chong thong tin sai o tang vat ly.
    """
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(20.0),  # chenh lech cuc lon van khong duoc ket luan
        measured_cop=1.1,
        is_defrosting=True,
    )
    assert result.status is FaultCode.INSUFFICIENT_DATA
    assert result.evaporating_c is None


def test_thieu_nhiet_do_dat_phai_noi_ro_la_chua_ket_luan_duoc():
    """`setpoint_c` nullable trong schema. Thieu no thi khong tinh duoc chenh lech nhiet do."""
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=None,
        pressure_bar=_pressure_for_approach(8.0),
        measured_cop=2.4,
    )
    assert result.status is FaultCode.INSUFFICIENT_DATA
    # Diem quan trong: nguoi van hanh khong duoc nham "khong co ket luan" thanh "may dang tot".
    assert result.ambiguity is not None
    assert "KHONG phai" in result.ambiguity


def test_thieu_ap_suat_phai_noi_ro_la_chua_ket_luan_duoc():
    """Seed tra ve `pressure_bar = None` cho mau dang xa bang, nen duong nay co that trong DB."""
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=None,
        measured_cop=2.4,
    )
    assert result.status is FaultCode.INSUFFICIENT_DATA
    assert result.ambiguity is not None


def test_nhan_moi_chat_la_thi_noi_loi_chu_khong_am_thang_bo_qua():
    """Loi cau hinh khac voi thieu du lieu.

    Nhan moi chat la chuoi tu do trong DB. Neu 'R404a' bi am thang coi la khong biet roi tra ve
    INSUFFICIENT_DATA, thi mot loi go chu se lam thiet bi nay roi khoi moi chan doan ma khong ai
    biet - bao cao van "xanh".
    """
    with pytest.raises(RefrigerantError):
        diagnose_low_side(
            refrigerant_label="R404a",
            setpoint_c=SETPOINT_C,
            pressure_bar=_pressure_for_approach(8.0),
            measured_cop=2.4,
        )


def test_ap_suat_am_la_loi_cam_bien_khong_phai_trang_thai_vat_ly():
    with pytest.raises(RefrigerantError):
        diagnose_low_side(
            refrigerant_label=LABEL,
            setpoint_c=SETPOINT_C,
            pressure_bar=-1.5,
            measured_cop=2.4,
        )


# --------------------------------------------------------------------------- #
# 2. Bon chu ky su co
# --------------------------------------------------------------------------- #
def test_dan_bay_hoi_nong_hon_kho_thi_mat_kha_nang_lam_lanh():
    """Chenh lech am: nhiet khong the tu chay tu kho sang dan bay hoi.

    Day KHONG phai la "may kem hieu qua" ma la "may khong lam lanh duoc nua" - khac biet rat lon
    ve mat HACCP vi hang hoa dang am dan. Do do phai la CONFIRMED, khong phai POSSIBLE.
    """
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(-4.0),  # T_evap = -21 C, nong hon kho -25 C
        measured_cop=0.9,
    )
    assert result.status is FaultCode.NO_COOLING_CAPABILITY
    assert result.approach_k is not None and result.approach_k < 0

    capability = _finding(result, FaultCode.NO_COOLING_CAPABILITY)
    assert capability is not None
    assert capability.confidence is Confidence.CONFIRMED
    assert "HACCP" in capability.remediation_text if False else "HACCP" in capability.remedy


def test_chenh_lech_qua_lon_thi_loai_duoc_dan_nong():
    """Chenh lech lon hon nguong: nguyen nhan chac chan o phia thap.

    Gia tri cua ket luan nay nam o cho bi loai: dan nong ban day T_cond LEN, khong keo T_evap
    xuong sau. Noi duoc "khong phai dan nong" da tiet kiem cho tho sua chua mot lan thao ve sinh
    dan nong vo ich.
    """
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(APPROACH_LOW_SIDE_FAULT_K + 3.0),
        measured_cop=1.6,
    )
    assert result.status is FaultCode.EVAPORATOR_FROST

    condenser = _finding(result, FaultCode.CONDENSER_FOULING)
    assert condenser is not None
    assert condenser.confidence is Confidence.RULED_OUT
    assert condenser.remedy == NO_REMEDIATION

    # Va phai noi thang la chua tach duoc dong bang khoi thieu gas.
    assert result.ambiguity is not None
    assert "xa bang" in result.ambiguity


def test_hai_nguyen_nhan_cua_chenh_lech_lon_deu_phai_la_likely_khong_cai_nao_chac_hon():
    """Mot mau don le khong tach duoc dong bang khoi thieu gas.

    Neu mot trong hai duoc gan CONFIRMED thi do la mot loi ket luan tu tin khong co bang chung -
    dung loai loi ma module nay sinh ra de tranh.
    """
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(APPROACH_LOW_SIDE_FAULT_K + 3.0),
        measured_cop=1.6,
    )
    frost = _finding(result, FaultCode.EVAPORATOR_FROST)
    undercharge = _finding(result, FaultCode.UNDERCHARGE)
    assert frost is not None and undercharge is not None
    assert frost.confidence is Confidence.LIKELY
    assert undercharge.confidence is Confidence.LIKELY


def test_chenh_lech_qua_hep_thi_nghi_may_nen_khong_tao_du_chenh_ap():
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(MIN_EFFECTIVE_APPROACH_K - 0.5),
        measured_cop=2.0,
    )
    assert result.status is FaultCode.COMPRESSOR_WEAR
    assert result.approach_k < MIN_EFFECTIVE_APPROACH_K
    # Chua tach duoc may nen mon / van tiet luu / thua moi chat -> phai noi ra.
    assert result.ambiguity is not None
    assert "qua nhiet" in result.ambiguity


def test_binh_thuong_va_cop_binh_thuong_thi_khong_sinh_chan_doan():
    """Khong duoc bịa ra su co khi moi thu binh thuong.

    Mot he thong chan doan luon tra ve it nhat mot nguyen nhan "POSSIBLE" se bi nguoi van hanh bo
    qua toan bo, ke ca luc no dung.
    """
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(8.0),
        measured_cop=3.1,
        cop_anomalously_low=False,
    )
    assert result.status is FaultCode.HEALTHY
    assert result.ambiguity is None

    codes = {finding.code for finding in result.findings}
    assert codes == {FaultCode.UNDERCHARGE, FaultCode.EVAPORATOR_FROST}
    assert all(finding.confidence is Confidence.RULED_OUT for finding in result.findings)


def test_phia_thap_binh_thuong_ma_cop_thap_thi_phai_huong_len_phia_cao():
    """Dung tinh huong ma logic cu ket luan sai.

    Logic cu: COP < 2.5 -> "ro ri moi chat". Nhung ro ri la nguyen nhan cua PHIA THAP, va phia
    thap dang binh thuong. Bao "ro ri" o day se dua tho di nap gas trong khi van de la dan nong
    ban hoac may nen mon - nap gas xong COP van thap, va mat them tien moi chat.
    """
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(8.0),
        measured_cop=1.9,
        cop_anomalously_low=True,
    )
    assert result.status is FaultCode.HEALTHY

    undercharge = _finding(result, FaultCode.UNDERCHARGE)
    assert undercharge is not None
    assert undercharge.confidence is Confidence.RULED_OUT

    condenser = _finding(result, FaultCode.CONDENSER_FOULING)
    compressor = _finding(result, FaultCode.COMPRESSOR_WEAR)
    assert condenser is not None and compressor is not None
    assert condenser.confidence is Confidence.POSSIBLE
    assert compressor.confidence is Confidence.POSSIBLE


def test_khong_tach_duoc_dan_nong_khoi_may_nen_thi_phai_khai_bao():
    """Rang cuc cua bat bien so 2: khong du nhiet do ngung tu thi phai noi la khong tach duoc."""
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(8.0),
        measured_cop=1.9,
        cop_anomalously_low=True,
    )
    assert result.ambiguity is not None
    assert "KHONG tach duoc" in result.ambiguity
    # Va phai chi ra phep do nao giai quyet duoc - day la thu khach hang can de quyet dinh dau tu
    # them cam bien.
    assert "phai cao" in result.ambiguity or "nhiet do ngung tu" in result.ambiguity


def test_khong_duoc_dung_nhiet_do_trong_kho_thay_cho_nhiet_do_moi_truong():
    """Ambiguity phai canh bao ro ve cai bay nay.

    Nhiet do trong kho (-25 C) thap hon nhiet do moi truong (~35 C) khoang 60 K. Dung no lam
    nhiet do giai nhiet se cho ra T_cond thap hon ca T_evap, va COP Carnot tinh ra se am hoac
    vo nghia - mot con so sai hoanh trang trong bao cao co ky.
    """
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(8.0),
        measured_cop=1.9,
        cop_anomalously_low=True,
    )
    assert result.ambiguity is not None
    assert "khong duoc dung nhiet do trong kho" in result.ambiguity


def test_gia_thiet_phai_duoc_tra_ve_de_nguoi_doc_bao_cao_biet_dau_la_so_chon():
    """Theo dung quy uoc o `ai_energy.py`: he so ky su chon phai xuat hien trong `assumptions`."""
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(8.0),
        measured_cop=3.0,
    )
    assert result.assumptions["max_healthy_approach_k"] == MAX_HEALTHY_APPROACH_K
    assert result.assumptions["approach_low_side_fault_k"] == APPROACH_LOW_SIDE_FAULT_K
    assert result.assumptions["min_effective_approach_k"] == MIN_EFFECTIVE_APPROACH_K


def test_moi_bang_chung_deu_phai_co_so_cu_the_de_ky_su_khac_kiem_tra_lai_duoc():
    """Evidence khong duoc la cau chung chung kieu 'he thong bat thuong'.

    Mot chan doan ma tho sua chua khong doi chieu lai duoc thi khong khang dinh duoc - va mot bao
    cao M&V khong khang dinh duoc thi khong dung duoc de tinh tien tiet kiem.
    """
    result = diagnose_low_side(
        refrigerant_label=LABEL,
        setpoint_c=SETPOINT_C,
        pressure_bar=_pressure_for_approach(APPROACH_LOW_SIDE_FAULT_K + 3.0),
        measured_cop=1.6,
    )
    for finding in result.findings:
        assert finding.evidence, f"{finding.code.value} khong co evidence"
        assert finding.evidence.strip() == finding.evidence
        if finding.confidence is not Confidence.RULED_OUT:
            assert finding.remedy, f"{finding.code.value} co ket luan ma khong co viec can lam"


# --------------------------------------------------------------------------- #
# 3. Tach dong bang khoi thieu gas theo dien bien thoi gian
# --------------------------------------------------------------------------- #
def test_mot_mau_sau_xa_bang_thi_khong_du_de_ket_luan():
    """Mot diem khong noi duoc 'co hoi phuc hay khong'. Ket luan tu mot mau la doan."""
    assert separate_frost_from_undercharge([(18.0, True)]) is None
    assert separate_frost_from_undercharge([]) is None
    assert separate_frost_from_undercharge([(18.0, False), (17.5, False)]) is None
    assert MIN_POST_DEFROST_SAMPLES == 2


def test_dang_hinh_rang_cua_la_dong_bang():
    """Sau xa bang chenh lech nho lai ro ret, roi lon dan tro lai -> bang tan roi dong lai."""
    series = [
        (8.0, False), (14.0, False), (19.0, False),
        (7.5, True),                       # vua xa bang xong: bang tan
        (14.0, False), (19.5, False),
        (7.8, True),                       # chu ky tiep theo: lai hoi phuc
    ]
    assert separate_frost_from_undercharge(series) is FaultCode.EVAPORATOR_FROST


def test_sut_deu_khong_hoi_phuc_la_thieu_moi_chat():
    """Khoi luong moi chat khong tu hoi phuc sau xa bang, nen chenh lech cu lon dan deu deu."""
    series = [
        (16.0, False), (17.0, False), (18.0, True), (18.5, False), (19.5, True), (20.5, False),
    ]
    result = separate_frost_from_undercharge(series)
    assert result is FaultCode.UNDERCHARGE
    # Dao dong giua cac mau sau xa bang phai nam duoi nguong hoi phuc.
    assert (19.5 - 18.0) < MIN_DEFROST_RECOVERY_K


def test_dao_dong_duoi_nguong_hoi_phuc_thi_khong_duoc_goi_la_dong_bang():
    """Bien do dung bang nguong: phai nho hon nguong moi goi la khong hoi phuc."""
    flat = [(18.0, True), (18.0 + MIN_DEFROST_RECOVERY_K - 0.1, True)]
    assert separate_frost_from_undercharge(flat) is FaultCode.UNDERCHARGE

    sawtooth = [(18.0, True), (18.0 + MIN_DEFROST_RECOVERY_K, True)]
    assert separate_frost_from_undercharge(sawtooth) is FaultCode.EVAPORATOR_FROST


# --------------------------------------------------------------------------- #
# 4. Mien chan doan phai khop voi mien seed sinh ra (chong hai nguon lech nhau)
# --------------------------------------------------------------------------- #
def test_toan_bo_doi_tau_lanh_trong_seed_duoc_chan_doan_la_khong_co_su_co_phia_thap(seeded: Session):
    """Seed sinh chenh lech 6-9 K, con chan doan bao dong tren 15 K - nen seed phai ra HEALTHY.

    Test nay bat mot lop loi ma khong test don vi nao bat duoc: neu hai mien nay lech nhau (vi du
    doi mien thiet ke trong seed ma quen doi nguong chan doan) thi he thong se bao dong hang loat
    tren du lieu binh thuong, hoac nguoc lai - bo lot su co that. Chung cung cam mien thiet ke
    khong duoc roi khoi mien chan doan.
    """
    kinds = [kind.value for kind in REFRIGERATION_KINDS]
    equipments = list(seeded.scalars(select(Equipment).where(Equipment.kind.in_(kinds))))
    assert equipments, "Seed khong co thiet bi lanh nao - test nay khong con y nghia"

    for equipment in equipments:
        if equipment.setpoint_c is None:
            continue
        pressure = _pressure_for_approach(7.5, equipment.setpoint_c, equipment.refrigerant or LABEL)
        result = diagnose_low_side(
            refrigerant_label=equipment.refrigerant,
            setpoint_c=equipment.setpoint_c,
            pressure_bar=pressure,
            measured_cop=equipment.design_cop,
        )
        assert result.status is FaultCode.HEALTHY, (
            f"{equipment.code} ({equipment.refrigerant}, setpoint {equipment.setpoint_c} C) bi "
            f"chan doan la {result.status.value} du dang o giua mien thiet ke"
        )


def test_nguong_chan_doan_phai_nhat_quan_voi_mien_thiet_ke():
    """Mien thiet ke phai nam tron trong mien "khong bao dong", neu khong hai bo nguong tu mau thuan."""
    from app.seed import EVAP_APPROACH_K

    assert EVAP_APPROACH_K[0] > MIN_EFFECTIVE_APPROACH_K
    assert EVAP_APPROACH_K[1] < MAX_HEALTHY_APPROACH_K
    assert MAX_HEALTHY_APPROACH_K < APPROACH_LOW_SIDE_FAULT_K


def test_moi_thiet_bi_lanh_trong_seed_deu_chan_doan_duoc_tu_du_lieu_that(seeded: Session):
    """Chay chan doan tren ap suat seed da sinh ra, de chac khong co duong nao noi loi.

    Seed tra ve `pressure_bar = None` cho mau dang xa bang; chan doan phai xu ly duoc ca hai
    truong hop ma khong tung loi.
    """
    kinds = [kind.value for kind in REFRIGERATION_KINDS]
    equipments = list(seeded.scalars(select(Equipment).where(Equipment.kind.in_(kinds))))
    assert equipments

    from app.models import TelemetrySample

    checked = 0
    for equipment in equipments:
        samples = list(
            seeded.scalars(
                select(TelemetrySample)
                .where(TelemetrySample.equipment_id == equipment.id)
                .limit(50)
            )
        )
        for sample in samples:
            result = diagnose_low_side(
                refrigerant_label=equipment.refrigerant,
                setpoint_c=equipment.setpoint_c,
                pressure_bar=sample.pressure_bar,
                measured_cop=sample.cop,
                is_defrosting=sample.status == EquipmentStatus.DEFROST.value,
            )
            assert result.status in set(FaultCode)
            checked += 1
    assert checked > 0


def test_lo_hoi_trong_seed_khong_bao_ro_ri(seeded: Session):
    """Rang cu the bat bien so 1 tren du lieu that: lo hoi phai ra INSUFFICIENT_DATA."""
    boilers = list(
        seeded.scalars(select(Equipment).where(Equipment.kind == EquipmentKind.BOILER.value))
    )
    assert boilers, "Seed khong co lo hoi - test nay khong con y nghia"

    for boiler in boilers:
        assert boiler.refrigerant is None
        result = diagnose_low_side(
            refrigerant_label=boiler.refrigerant,
            setpoint_c=boiler.setpoint_c,
            pressure_bar=9.0,
            measured_cop=None,
        )
        assert result.status is FaultCode.INSUFFICIENT_DATA
