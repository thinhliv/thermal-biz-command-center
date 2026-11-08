"""Chan doan su co he thong lanh tu chuoi P-T, thay vi mot nguong COP hardcode.

LY DO MODULE NAY TON TAI
------------------------
`ai_energy.py` so COP voi `COP_LEAK_ABSOLUTE = 2.5` va, khi thap hon, ket luan luon la "ro ri
moi chat". Chinh docstring cua `thermal.py` da thua nhan COP thap co hai nguyen nhan (thieu gas
HOAC ban dan nong), nhung phia chan doan chi tra ve mot. Con hai nguyen nhan nua - dong bang dan
bay hoi va mon may nen. Bon nguyen nhan nay co cach chua khac nhau va chi phi khac nhau, nen mot
ket luan sai se dua tho sua chua di sai huong va lam mat thoi gian kho dang chay hang.

Cach tach bon nguyen nhan: COP thap chi la TRIEU CHUNG. Nguyen nhan nam o ba cho khac nhau trong
chu ky - dan bay hoi (phia thap), dan nong (phia cao), va ban than may nen. Vi vay phai doi ap
suat DO duoc thanh nhiet do, roi xem phia nao lech. Do la viec cua `app.services.refrigerant`.

GIOI HAN DU LIEU HIEN TAI - doc ky truoc khi mo rong module nay
---------------------------------------------------------------
`telemetry_samples` chi co MOT cot `pressure_bar`, va voi thiet bi lanh no mang nghia ap suat PHIA
THAP (dan bay hoi). Schema khong co ap suat phia cao, cung khong co nhiet do moi truong ngoai
(`temperature_c` cua telemetry la nhiet do BUONG/SAN PHAM, khong phai nhiet do moi truong - dung
no thay cho moi truong la bia du lieu). Cho nen T_cond KHONG suy ra duoc tu du lieu do.

Khong co T_cond thi khong tinh duoc COP Carnot, va do do khong tach duoc "ban dan nong" khoi
"mon may nen" - hai ben deu lam COP sut trong khi phia thap van binh thuong.

Vi vay module nay:
  - chan doan DUOC nhung gi phia dan bay hoi noi ra: thieu gas, dong bang, hoac khong con kha
    nang lam lanh;
  - voi phia dan nong va may nen: chi THU HEP pham vi va noi ro con mo ho o cho nao, kem theo
    phep do nao se giai quyet duoc. Khong bao gio doan.

Cac ham trong module nay nhan gia tri nguyen thuy (khong nhan ORM object) de giu chung thuan tuyet
doi va de test. Phan doc DB va phia ra API nam o goi cua chung.

CAC NGUON KHONG DUOC BIA
------------------------
Khong mot con so nhiet vat ly nao duoc tinh trong file nay: moi thu lay tu `refrigerant.py`
(CoolProp). Cac nguong o day la PHUONG AN van hanh do ky su chon, khong phai so lieu do duoc -
theo dung quy uoc da ghi o `ai_energy.py:57` - va duoc tra ve trong `assumptions` de nguoi doc
bao cao biet dau la gia thiet.

Loi cau hinh (nhan moi chat khong co trong bang, ap suat am) se noi len thanh `RefrigerantError`
chu khong bi bien thanh INSUFFICIENT_DATA: do la loi can sua, khong phai mot mau thieu du lieu.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import refrigerant


class FaultCode(str, Enum):
    """Bon nguyen nhan lam COP sut, cong hai trang thai khong phai su co co hoc."""

    #: Thieu moi chat (ro ri, hoac nap chua du). Chua: tim cho ro ri, hut chan khong, nap lai.
    UNDERCHARGE = "UNDERCHARGE"
    #: Dan bay hoi dong bang/tuyet: tro nhiet tang nen T_evap bi keo xuong. Chua: xu ly chu ky xa
    #: bang, kiem tra quat dan lanh va do am trong kho.
    EVAPORATOR_FROST = "EVAPORATOR_FROST"
    #: Dan nong ban / giai nhiet kem: T_cond tang. KHONG xac dinh duoc voi du lieu hien tai.
    CONDENSER_FOULING = "CONDENSER_FOULING"
    #: May nen mon: hai phia van dung nhung COP van thap. KHONG xac dinh duoc voi du lieu hien tai.
    COMPRESSOR_WEAR = "COMPRESSOR_WEAR"
    #: T_evap nong hon nhiet do dat cua kho: nhiet khong the tu chay tu kho sang moi chat, tuc la
    #: thiet bi KHONG con kha nang lam lanh. Nghiem trong nhat ve mat HACCP.
    NO_COOLING_CAPABILITY = "NO_COOLING_CAPABILITY"
    #: Phia dan bay hoi binh thuong. Neu COP van thap thi van de nam o phia cao hoac o may nen,
    #: va `ambiguity` se noi ro la chua tach duoc hai ben do.
    HEALTHY = "HEALTHY"
    #: Thieu du lieu de ket luan. Tra ve trang thai nay tot hon tra ve mot doan sai: chan doan sai
    #: duoc tin nhu that, con thieu du lieu thi nguoi doc biet phai di do them.
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Confidence(str, Enum):
    """Muc do chac chan cua mot chan doan.

    DAY KHONG PHAI XAC SUAT. He thong khong du du lieu de uoc luong xac suat that, va mot con so
    nhu 0.73 se duoc doc nhu mot phep tinh co that dang sau no. Thang bac nay chi noi "bang chung
    manh den dau".
    """

    #: Du lieu doi chieu truc tiep, khong con cach giai thich nao khac hop ly.
    CONFIRMED = "CONFIRMED"
    #: Bang chung ung ho manh, nhung con it nhat mot nguyen nhan khac chua loai duoc.
    LIKELY = "LIKELY"
    #: Khong loai tru duoc, nhung bang chung yeu.
    POSSIBLE = "POSSIBLE"
    #: Da loai duoc bang du lieu. Giu lai trong ket qua de nguoi doc thay vi sao loai.
    RULED_OUT = "RULED_OUT"


#: Chenh lech nhiet do dan bay hoi cho phep: `setpoint_c - T_evap`, tinh bang K.
#:
#: Dan bay hoi phai LANH HON khong khi trong kho thi nhiet moi chay vao duoc, nen chenh lech nay
#: luon duong. Cang lon thi may cang ton dien (tran COP Carnot thap xuong), nhung qua nho thi dan
#: bay hoi phai lon vo ly. Mien 6-10 K la thiet ke thong thuong cho kho lanh.
#:
#: Day la PHUONG AN van hanh do ky su chon, khong phai so lieu do duoc va khong phai tinh chat
#: nhiet vat ly cua moi chat. Voi mot kho cu the, nguon dung la ho so thiet ke cua kho do.
MAX_HEALTHY_APPROACH_K = 12.0

#: Tren muc nay, chenh lech lon den noi nguyen nhan gan nhu chac chan nam o phia thap: dan nong
#: ban hay may nen mon deu day T_cond LEN, chu khong keo T_evap xuong sau nhu the nay.
APPROACH_LOW_SIDE_FAULT_K = 15.0

#: Duoi muc nay dan bay hoi gan nhu khong lam viec: may nen khong bom duoc, thieu moi chat nghiem
#: trong, hoac van tiet luu mo qua lon.
MIN_EFFECTIVE_APPROACH_K = 1.0

#: Muc sut chenh lech nhiet do toi thieu giua ngay TRUOC va ngay SAU mot chu ky xa bang de coi la
#: "bang co tan that su". Duoi muc nay thi dao dong chi la nhieu cam bien hoac thay doi phu tai.
#: La PHUONG AN do ky su chon.
MIN_DEFROST_RECOVERY_K = 3.0

#: So mau sau xa bang toi thieu de bat dau doi chieu. Khong phai de lay trung binh: mot lan hoi
#: phuc ro ret sau xa bang da la bang chung du, vi thieu moi chat thi khong bao gio hoi phuc duoc.
#: Nguong nay chi chan truong hop qua it mau de noi bat cu dieu gi.
MIN_POST_DEFROST_SAMPLES = 2

#: Khong can hanh dong nao. Dung cho cac `Finding` da bi loai, de khoi phai bia ra mot viec can
#: lam cho mot nguyen nhan khong ton tai.
NO_REMEDIATION = ""

#: Mot ket qua "thieu du lieu" rat de bi nguoi doc hieu thanh "khong co van de". Cau nay duoc gan
#: vao MOI ket qua INSUFFICIENT_DATA, o mot cho duy nhat, de khong mot duong code nao quen no.
_NOT_A_HEALTHY_CONCLUSION = (
    "Day KHONG phai la ket luan thiet bi dang binh thuong - khong co canh bao khong co nghia la "
    "khong co su co."
)


@dataclass(frozen=True)
class Finding:
    """Mot nguyen nhan candidate, kem bang chung va viec can lam."""

    code: FaultCode
    confidence: Confidence
    #: Vi sao ket luan nhu vay, viet sao cho mot ky su khac kiem tra lai duoc tu chinh so lieu.
    #: Khong phai loi thoong bao chung chung kieu "he thong bat thuong".
    evidence: str
    #: Viec can lam tiep theo. Day la kien thuc nganh (quy trinh), khong phai du lieu kinh doanh,
    #: nen nam o day la hop ly. KHONG chua chi phi: gia sua chua o Viet Nam chua co nguon, va
    #: mot con so khong co nguon thi khong duoc xuat hien trong bao cao.
    remedy: str


@dataclass(frozen=True)
class LowSideDiagnosis:
    """Ket qua chan doan phia dan bay hoi cua mot mau telemetry."""

    #: Nhiet do bao hoa suy ra tu ap suat DO duoc. None khi khong co ap suat, thiet bi khong phai
    #: thiet bi lanh, hoac dang xa bang.
    evaporating_c: float | None
    #: `setpoint_c - evaporating_c`, tinh bang K. None khi thieu mot trong hai so.
    approach_k: float | None
    status: FaultCode
    findings: tuple[Finding, ...]
    #: Con mo ho gi, va phep do nao se giai quyet. None khi chan doan da ro rang.
    ambiguity: str | None
    #: Cac gia thiet da dung, de nguoi doc bao cao biet dau la so do duoc va dau la phuong an chon.
    assumptions: dict[str, float]


def _assumptions() -> dict[str, float]:
    return {
        "max_healthy_approach_k": MAX_HEALTHY_APPROACH_K,
        "approach_low_side_fault_k": APPROACH_LOW_SIDE_FAULT_K,
        "min_effective_approach_k": MIN_EFFECTIVE_APPROACH_K,
    }


def _insufficient(detail: str, next_step: str) -> LowSideDiagnosis:
    """Ket qua khi khong du du lieu de ket luan.

    `detail` noi thieu gi, `next_step` noi lam gi de co du. Ca hai duoc giu lai trong `ambiguity`
    vi nguoi van hanh can ca hai moi hanh dong duoc; bo mot trong hai thi ket qua chi con la mot loi
    tu choi khong dung duoc.
    """
    return LowSideDiagnosis(
        evaporating_c=None,
        approach_k=None,
        status=FaultCode.INSUFFICIENT_DATA,
        findings=(),
        ambiguity=f"{detail} {next_step} {_NOT_A_HEALTHY_CONCLUSION}",
        assumptions=_assumptions(),
    )


def diagnose_low_side(
    *,
    refrigerant_label: str | None,
    setpoint_c: float | None,
    pressure_bar: float | None,
    measured_cop: float | None,
    cop_anomalously_low: bool = False,
    is_defrosting: bool = False,
) -> LowSideDiagnosis:
    """Chan doan nguyen nhan su co tu phia dan bay hoi cua MOT mau telemetry.

    Args:
        refrigerant_label: nhan moi chat trong ho so thiet bi (vi du "R404A"). NULL voi lo hoi.
        setpoint_c: nhiet do dat cua kho.
        pressure_bar: ap suat PHIA THAP do duoc (dan bay hoi).
        measured_cop: COP do duoc, None khi khong co. Duoc trich dan vao `evidence` de nguoi doc
            doi chieu lai duoc; ban than no KHONG quyet dinh ket luan (xem `cop_anomalously_low`).
        cop_anomalously_low: COP co thap hon mong doi hay khong. Goi ham nay phai tu quyet dinh
            vi no da co `design_cop` va da tinh `cop_gap_pct` trong `thermal.assess_health`; tinh
            lai o day se tao ra hai nguon co the lech nhau cho cung mot ket luan. True thi
            `measured_cop` phai khac None, vi khong co COP thi khong the noi COP thap.
        is_defrosting: mau nay co thuoc chu ky xa bang khong.

    Khi chua ket luan duoc thi `ambiguity` noi thang da thu hep den dau va can do them gi; khi da
    ket luan duoc thi `ambiguity` la None. Day la diem khac biet cot loi so voi logic cu: logic cu
    luon noi "ro ri" khi COP thap, con o day neu du lieu chi cho phep thu hep pham vi thi ket qua
    khong gia vo da biet ro.
    """
    if is_defrosting:
        # Trong luc xa bang, dan bay hoi duoc nong hoa khi nen vao de lam tan bang. Ap suat luc
        # nay khong con la ap suat bay hoi on dinh, nen moi ket luan ve chenh lech nhiet do deu
        # vo nghia. Chan doan trong luc nay se bao dong sai mot cach co he thong.
        return _insufficient(
            detail="Thiet bi dang o chu ky xa bang, ap suat phia thap khong on dinh.",
            next_step="Chan doan lai sau khi chu ky xa bang ket thuc.",
        )

    # `refrigerant_label` NULL cho thiet bi khong phai thiet bi lanh (lo hoi). Do khong phai loi:
    # lo hoi danh gia bang hieu suat eta, khong co chu ky lanh de chan doan.
    evaporating_c = refrigerant.saturation_temperature_c(refrigerant_label, pressure_bar)
    if evaporating_c is None or setpoint_c is None:
        missing = []
        if evaporating_c is None:
            missing.append("ap suat phia thap hoac nhan moi chat")
        if setpoint_c is None:
            missing.append("nhiet do dat cua kho")
        return _insufficient(
            detail=f"Khong du du lieu de chan doan. Thieu: {', '.join(missing)}.",
            next_step="Bo sung cam bien hoac ho so thiet bi truoc khi chan doan.",
        )

    approach_k = round(setpoint_c - evaporating_c, 2)
    evaporating_c = round(evaporating_c, 2)

    if approach_k < 0:
        # Nhiet khong the tu chay tu kho sang dan bay hoi khi dan bay hoi nong hon kho. Neu so
        # lieu dung thi thiet bi da mat hoan toan kha nang lam lanh.
        return LowSideDiagnosis(
            evaporating_c=evaporating_c,
            approach_k=approach_k,
            status=FaultCode.NO_COOLING_CAPABILITY,
            findings=(
                Finding(
                    code=FaultCode.NO_COOLING_CAPABILITY,
                    confidence=Confidence.CONFIRMED,
                    evidence=(
                        f"T_evap {evaporating_c} C nong hon nhiet do dat {setpoint_c} C (chenh lech "
                        f"{approach_k} K, am). Nhiet khong the tu chay tu kho sang dan bay hoi."
                    ),
                    remedy=(
                        "Kiem tra ngay: may nen co dang bom khong, muc moi chat, van tiet luu. Kho "
                        "nay khong giu duoc nhiet do HACCP - uu tien xu ly hang hoa truoc."
                    ),
                ),
                Finding(
                    code=FaultCode.UNDERCHARGE,
                    confidence=Confidence.LIKELY,
                    evidence=(
                        "Mat kha nang lam lanh thuong gap nhat khi thieu moi chat nghiem trong."
                    ),
                    remedy=(
                        "Tim cho ro ri truoc khi nap lai; nap ma khong bit thi se mat tiep va mat "
                        "them chi phi moi chat."
                    ),
                ),
            ),
            ambiguity=(
                "Chua phan biet duoc that su mat moi chat voi that su cam bien ap suat. Doi chieu "
                "ap suat phia thap bang dong ho ga gan may truoc khi ket luan cam bien hong."
            ),
            assumptions=_assumptions(),
        )

    if approach_k > APPROACH_LOW_SIDE_FAULT_K:
        return LowSideDiagnosis(
            evaporating_c=evaporating_c,
            approach_k=approach_k,
            status=FaultCode.EVAPORATOR_FROST,
            findings=(
                Finding(
                    code=FaultCode.EVAPORATOR_FROST,
                    confidence=Confidence.LIKELY,
                    evidence=(
                        f"Chenh lech {approach_k} K vuot nguong {APPROACH_LOW_SIDE_FAULT_K} K: dan "
                        "bay hoi phai keo xuong rat sau moi tai duoc nhiet, dac trung cua lop bang "
                        "lam tang tro nhiet."
                    ),
                    remedy=(
                        "Kiem tra chu ky xa bang co chay va co ket thuc khong, quat dan lanh, do am "
                        "trong kho va do kin cua cua kho."
                    ),
                ),
                Finding(
                    code=FaultCode.UNDERCHARGE,
                    confidence=Confidence.LIKELY,
                    evidence=(
                        "Thieu moi chat cung keo T_evap xuong va lam COP sut - trieu chung giong het "
                        "dong bang khi chi nhin mot mau."
                    ),
                    remedy=(
                        "Doi chieu theo thoi gian bang `separate_frost_from_undercharge` truoc khi "
                        "quyet dinh nap gas hay sua chu ky xa bang."
                    ),
                ),
                Finding(
                    code=FaultCode.CONDENSER_FOULING,
                    confidence=Confidence.RULED_OUT,
                    evidence=(
                        "Dan nong ban lam T_cond tang, khong keo T_evap xuong sau den muc nay."
                    ),
                    remedy=NO_REMEDIATION,
                ),
            ),
            ambiguity=(
                "Dong bang dan bay hoi va thieu moi chat cho cung mot dau hieu khi chi nhin mot "
                "mau. Phan biet bang dien bien theo thoi gian xung quanh chu ky xa bang: bang thi "
                "hoi phuc sau xa bang, thieu gas thi sut deu va khong hoi phuc."
            ),
            assumptions=_assumptions(),
        )

    if approach_k < MIN_EFFECTIVE_APPROACH_K:
        return LowSideDiagnosis(
            evaporating_c=evaporating_c,
            approach_k=approach_k,
            status=FaultCode.COMPRESSOR_WEAR,
            findings=(
                Finding(
                    code=FaultCode.COMPRESSOR_WEAR,
                    confidence=Confidence.POSSIBLE,
                    evidence=(
                        f"Chenh lech chi {approach_k} K: dan bay hoi khong bi keo xuong, tuc la may "
                        "khong tao duoc chenh ap can thiet."
                    ),
                    remedy=(
                        "Do dong may nen, kiem tra ro ri noi bo giua khoang hut va khoang day, doi "
                        "chieu voi rung dong theo ISO 10816."
                    ),
                ),
                Finding(
                    code=FaultCode.UNDERCHARGE,
                    confidence=Confidence.POSSIBLE,
                    evidence=(
                        "Van tiet luu mo qua lon hoac thua moi chat cung lam chenh lech nhiet do "
                        "hep lai."
                    ),
                    remedy="Kiem tra do qua nhiet (superheat) tai dan bay hoi.",
                ),
            ),
            ambiguity=(
                "Chenh lech nhiet do hep co the do may nen mon, do van tiet luu, hoac do thua moi "
                "chat. Can them do qua nhiet va ap suat phia cao de tach ba nguyen nhan nay."
            ),
            assumptions=_assumptions(),
        )

    # Phia dan bay hoi binh thuong. Neu COP van thap thi van de nam o cho khac - va day chinh la
    # thong tin dat gia nhat ma logic cu khong dua ra duoc: no bao "ro ri" cho ca truong hop nay,
    # trong khi ro ri la nguyen nhan cua phia thap va phia thap dang binh thuong.
    findings: list[Finding] = [
        Finding(
            code=FaultCode.UNDERCHARGE,
            confidence=Confidence.RULED_OUT,
            evidence=(
                f"Chenh lech {approach_k} K nam trong mien thiet ke (toi da "
                f"{MAX_HEALTHY_APPROACH_K} K): dan bay hoi dang lam viec binh thuong."
            ),
            remedy=NO_REMEDIATION,
        ),
        Finding(
            code=FaultCode.EVAPORATOR_FROST,
            confidence=Confidence.RULED_OUT,
            evidence="Khong co dau hieu tang tro nhiet o dan bay hoi.",
            remedy=NO_REMEDIATION,
        ),
    ]
    ambiguity: str | None = None

    if cop_anomalously_low:
        findings.append(
            Finding(
                code=FaultCode.CONDENSER_FOULING,
                confidence=Confidence.POSSIBLE,
                evidence=(
                    f"COP do duoc {measured_cop} trong khi phia thap van binh thuong (chenh lech "
                    f"{approach_k} K, trong mien thiet ke), nen COP thap khong do dan bay hoi; "
                    "nguyen nhan nam o phia cao hoac o may nen."
                ),
                remedy=(
                    "Ve sinh dan nong, kiem tra quat dan nong va nhiet do moi truong giai nhiet."
                ),
            )
        )
        findings.append(
            Finding(
                code=FaultCode.COMPRESSOR_WEAR,
                confidence=Confidence.POSSIBLE,
                evidence="Cung pham vi voi ban dan nong: ca hai deu lam COP sut khi phia thap van dung.",
                remedy="Do dong may nen va doi chieu voi rung dong theo ISO 10816.",
            )
        )
        ambiguity = (
            "KHONG tach duoc ban dan nong khoi mon may nen voi du lieu hien tai: ca hai deu nam o "
            "phia cao, va muon tach thi can nhiet do ngung tu. Nguon co the la cot ap suat phia cao "
            "trong telemetry, hoac nhiet do moi truong (khong duoc dung nhiet do trong kho thay cho "
            "nhiet do moi truong)."
        )

    return LowSideDiagnosis(
        evaporating_c=evaporating_c,
        approach_k=approach_k,
        status=FaultCode.HEALTHY,
        findings=tuple(findings),
        ambiguity=ambiguity,
        assumptions=_assumptions(),
    )


def separate_frost_from_undercharge(
    approach_series: list[tuple[float, bool]],
) -> FaultCode | None:
    """Tach dong bang dan bay hoi khoi thieu moi chat bang DIEN BIEN theo thoi gian.

    Day la cho ma mot mau don le khong du, va cung la cho ma kien thuc nganh thay the duoc cho
    cam bien ma kho chua co: hai su co nay cho cung mot chenh lech nhiet do lon, nhung khac nhau
    ve cach phan ung voi chu ky xa bang.

      - Dong bang: lop bang tan chay khi xa bang, tro nhiet giam, T_evap nang len -> chenh lech
        NHO lai ro ret sau moi chu ky, roi lon dan tro lai. Dang hinh rang cua.
      - Thieu moi chat: khoi luong moi chat khong tu hoi phuc sau xa bang -> chenh lech giam khong
        dang ke, va xu huong chung la tang dan theo thoi gian.

    Args:
        approach_series: danh sach `(approach_k, is_post_defrost)` theo thu tu thoi gian tang dan.
            `is_post_defrost` danh dau mau lay NGAY SAU khi ket thuc mot chu ky xa bang.

    Returns:
        `EVAPORATOR_FROST`, `UNDERCHARGE`, hoac None khi chua du bang chung (qua it mau sau xa bang,
        hoac khong co cap "truoc - sau" nao de doi chieu). None la ket qua hop le: doan sai o day
        se chi dinh sai cho ca mot dot sua chua.
    """
    post_defrost_count = sum(1 for _, is_post in approach_series if is_post)
    if post_defrost_count < MIN_POST_DEFROST_SAMPLES:
        return None

    # Do hoi phuc = chenh lech nhiet do NGAY TRUOC tru NGAY SAU mot chu ky xa bang. Dong bang thi
    # lop bang tan giup T_evap nang len nen chenh lech giam manh; thieu moi chat thi khoi luong moi
    # chat khong doi, chenh lech giu nguyen hoac tiep tuc tang (do hoi phuc am).
    recoveries = [
        approach_series[idx - 1][0] - value
        for idx, (value, is_post) in enumerate(approach_series)
        if is_post and idx > 0 and not approach_series[idx - 1][1]
    ]

    if not recoveries:
        # Khong co cap "truoc - sau xa bang" nao de doi chieu. Do dao dong GIUA cac mau sau xa
        # bang khong phai la tin hieu hoi phuc: no chi la nhieu, va dung no de ket luan la doan
        # mot nguyen nhan sua chua tu so lieu khong noi duoc gi.
        return None

    # Mot lan hoi phuc ro ret da du ket luan dong bang, vi thieu moi chat thi khoi luong moi chat
    # khong tu hoi phuc sau xa bang - day la mot bang chung ton tai, khong phai mot phep trung binh.
    if max(recoveries) >= MIN_DEFROST_RECOVERY_K:
        return FaultCode.EVAPORATOR_FROST
    return FaultCode.UNDERCHARGE
