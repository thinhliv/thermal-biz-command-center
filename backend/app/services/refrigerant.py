"""Tinh chat nhiet vat ly moi chat lanh, tinh bang CoolProp thay vi go tay.

Ly do module nay ton tai: `Equipment.refrigerant` chi la mot nhan chu (String(32)).
Khong co bat ky tinh chat nhiet vat ly nao dang sau nhan do, nen he thong khong the
doi ap suat do duoc thanh nhiet do bao hoa, va do do khong the biet T_evap / T_cond.
Khong co T_evap / T_cond thi khong co gioi han COP Carnot, va moi ket luan ve su co
chi la so sanh COP voi mot nguong hardcode.

QUY TAC BAT BUOC: khong mot hang so nhiet vat ly nao duoc go tay trong du an nay.
Mot con so go sai se di vao bao cao co ky ma khong ai phat hien duoc. Moi gia tri
o day deu duoc CoolProp tinh luc chay tu phuong trinh trang thai cua moi chat.

Nguon: CoolProp 8.0.0, giay phep MIT. Moi gia tri duoi day la ket qua CoolProp tinh luc
chay tu phuong trinh trang thai cua tung moi chat; khong co gia tri nao duoc go tay o day.
"""

from __future__ import annotations

from CoolProp.CoolProp import PropsSI


class RefrigerantError(ValueError):
    """Nhan moi chat khong nhan dien duoc, hoac diem lam viec ngoai vung vat ly hop le.

    Thua ke ValueError de khop voi `PeakShavingConfigError` trong ai_energy.py: day la loi
    cau hinh / du lieu dau vao, khong phai loi he thong.
    """


#: Nhan moi chat luu trong `Equipment.refrigerant` -> ten fluid cua CoolProp.
#:
#: Day la cau hinh phia SERVER. Client khong duoc truyen ten fluid tuy y: neu truyen duoc
#: thi mot nguoi goi co the khai "R404A" cho he thong dang chay NH3 va lam lech toan bo
#: chan doan. Bo khoa nay co tinh dung voi khoa cua `GWP_FACTORS` trong compliance.py
#: de hai bang khong bao gio lech nhau (co test khoa dieu nay).
COOLPROP_FLUIDS: dict[str, str] = {
    "R404A": "R404A",
    "R134a": "R134a",
    "R22": "R22",
    "NH3": "Ammonia",
}

#: Quy uoc lay DIEM SOI (bubble point, quality = 0).
#:
#: R404A la hon hop zeotropic nen co truot nhiet do (temperature glide): tai cung mot ap
#: suat, diem soi va diem suong cach nhau khoang 0.65 K. Phai chon nhat quan mot chieu,
#: neu khong COP Carnot cua hai thiet bi tinh theo hai quy uoc khac nhau se khong so
#: sanh duoc. Chon diem soi vi no la dau duoc do truc tiep o dan bay hoi.
_QUALITY_BUBBLE = 0

#: 0 K = -273.15 C. Dung de doi sang nhiet do tuyet doi vi COP Carnot bat buoc tinh
#: theo Kelvin; tinh theo Celsius se cho ra so am hoac vo nghia.
_KELVIN_OFFSET = 273.15


def known_refrigerants() -> list[str]:
    """Danh sach nhan moi chat hop le, dung de bao loi va dung cho test khoa voi seed."""
    return sorted(COOLPROP_FLUIDS)


def resolve_fluid(refrigerant: str | None) -> str | None:
    """Doi nhan moi chat trong DB sang ten fluid cua CoolProp.

    Tra ve None khi thiet bi khong phai thiet bi lanh (vi du lo hoi, `refrigerant` NULL).
    Do KHONG phai la loi: mot lo hoi khong co moi chat lanh la chuyen binh thuong.

    Raise RefrigerantError khi nhan co ton tai nhung khong nam trong bang. Im lang bo qua
    o day se khien thiet bi nay roi khoi moi chan doan nhiet ma khong ai biet.
    """
    if refrigerant is None:
        return None

    fluid = COOLPROP_FLUIDS.get(refrigerant)
    if fluid is None:
        raise RefrigerantError(
            f"Khong co tinh chat nhiet vat ly cho moi chat '{refrigerant}'. "
            f"Cac ma hop le: {', '.join(known_refrigerants())}. "
            "Them vao COOLPROP_FLUIDS truoc khi dung - khong duoc doan ten fluid."
        )
    return fluid


def saturation_temperature_c(refrigerant: str | None, pressure_bar: float | None) -> float | None:
    """Nhiet do bao hoa (C) cua moi chat tai ap suat do duoc.

    Day la buoc dau tien cua ca chuoi chan doan: cam bien ap suat la thu duy nhat co san
    tren he thong that, con nhiet do bao hoa thi khong do truc tiep duoc. Co nhiet do nay
    moi suy ra duoc T_evap va T_cond.

    Tra ve None khi thiet bi khong phai thiet bi lanh hoac khong co so lieu ap suat.
    Khong bao gio tra ve mot con so doan.
    """
    fluid = resolve_fluid(refrigerant)
    if fluid is None or pressure_bar is None:
        return None

    if pressure_bar <= 0:
        raise RefrigerantError(
            f"Ap suat bao hoa phai lon hon 0 bar, nhan duoc {pressure_bar}. "
            "Day la cam bien hong hoac du lieu dau vao sai, khong phai trang thai vat ly that."
        )

    try:
        return PropsSI("T", "P", pressure_bar * 1e5, "Q", _QUALITY_BUBBLE, fluid) - _KELVIN_OFFSET
    except ValueError as exc:
        raise RefrigerantError(
            f"Ap suat {pressure_bar} bar nam ngoai vung bao hoa cua '{refrigerant}' "
            f"(vuot diem toi han hoac khong co nghiem). CoolProp bao: {exc}"
        ) from exc


def saturation_pressure_bar(refrigerant: str | None, temperature_c: float | None) -> float | None:
    """Ap suat bao hoa (bar) cua moi chat tai mot nhiet do.

    Chieu nguoc lai cua `saturation_temperature_c`. Dung de kiem tra du lieu: neu nhiet do
    bay hoi thiet ke la -30 C thi ap suat trong telemetry phai nam gan gia tri ham nay
    tra ve. Lech nhieu thi hoac la cam bien sai, hoac la du lieu seed khong nhat quan
    ve mat nhiet dong hoc.
    """
    fluid = resolve_fluid(refrigerant)
    if fluid is None or temperature_c is None:
        return None

    try:
        return PropsSI("P", "T", temperature_c + _KELVIN_OFFSET, "Q", _QUALITY_BUBBLE, fluid) / 1e5
    except ValueError as exc:
        raise RefrigerantError(
            f"Nhiet do {temperature_c} C nam ngoai vung bao hoa cua '{refrigerant}' "
            f"(thap hon diem ba hoac cao hon diem toi han). CoolProp bao: {exc}"
        ) from exc


def critical_temperature_c(refrigerant: str | None) -> float | None:
    """Nhiet do toi han (C). Tren muc nay moi chat khong bao gio ngung tu, nen khong co
    dan nong nao giai nhiet duoc - dung de bac cac gia tri T_cond vo ly."""
    fluid = resolve_fluid(refrigerant)
    if fluid is None:
        return None
    return PropsSI("Tcrit", fluid) - _KELVIN_OFFSET


def carnot_cop(evap_c: float | None, cond_c: float | None) -> float | None:
    """COP ly tuong (gioi han tren) cua chu trinh Carnot giua hai nguon nhiet.

        COP_carnot = T_evap / (T_cond - T_evap)      [Kelvin]

    Day la tran vat ly cua moi may lanh: khong thiet bi that nao vuot qua duoc. Gia tri
    do cho biet mot COP thap la do may co van hay do dieu kien van hanh von da khac nghiet.
    Kho -35 C giai nhiet ra moi truong 40 C co COP Carnot thap hon nhieu so kho +7 C giai
    nhiet ra 35 C, nen so sanh COP thoi giua hai kho nay la vo nghia.

    Tra ve None khi thieu du lieu. Raise khi T_cond <= T_evap: do la du lieu sai, vi nhiet
    tu khong the tu chay tu noi lanh sang noi nong.
    """
    if evap_c is None or cond_c is None:
        return None

    evap_k = evap_c + _KELVIN_OFFSET
    cond_k = cond_c + _KELVIN_OFFSET

    if evap_k <= 0 or cond_k <= 0:
        raise RefrigerantError(
            f"Nhiet do tuyet doi phai duong, nhan duoc T_evap={evap_c} C, T_cond={cond_c} C."
        )

    delta = cond_k - evap_k
    if delta <= 0:
        raise RefrigerantError(
            f"T_cond ({cond_c} C) phai lon hon T_evap ({evap_c} C). "
            "Chenh lech nay la du lieu dau vao sai, khong phai trang thai vat ly that."
        )

    return round(evap_k / delta, 3)


def second_law_efficiency(measured_cop: float | None, carnot: float | None) -> float | None:
    """Hieu suat luat hai (COP do duoc / COP Carnot), dang ti le 0..1.

    Con so nay moi la thu so sanh duoc GIUA cac thiet bi khac nhau: mot may COP 2.8 o
    kho -35 C co the hieu qua hon mot may COP 3.6 o kho +2 C. Hien thi theo % va luon
    nhan danh la gia tri DO duoc suy ra tu COP that, khong phai uoc luong.
    """
    if measured_cop is None or carnot is None or carnot <= 0:
        return None
    return round(measured_cop / carnot, 4)
