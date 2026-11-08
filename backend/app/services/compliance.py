"""Dich vu Kiem toan An toan Thuc pham HACCP va Bao cao Phat thai Carbon ESG (Scope 1 & 2).

1. HACCP Food Safety Compliance:
   - Danh sach diem kiem soat toi han (CCP) lay tu SO CAU HINH: thiet bi nao co
     `Equipment.haccp_limit_c` thi moi la CCP. Khong loc theo loai thiet bi, vi loc theo loai se
     bo sot ham cap dong gio nhanh (BLAST_FREEZER) - mat xich ngat nhat cua chuoi thuy hai san -
     va lai dem ca cum may nen (nhiet do dich, khong phai nhiet do san pham) vao bao cao an toan
     thuc pham.
   - Moi tai san doi chieu voi nguong cua CHINH no (kho mat +5 C, kho dong -18 C), nen ti le tuan
     thu tong hop khong tron lan hai quan the khac ban chat.
   - Khong co mau nhiet do -> NO_DATA voi compliance_pct = None. Khong duoc tinh la "tuan thu
     100%": mot kho khong co du lieu la mot kho CHUA DUOC CHUNG MINH la an toan.

2. ESG Scope 1 & Scope 2 Carbon Footprint:
   - Scope 1 (truc tiep): ro ri moi chat lanh, GWP theo IPCC AR5. Loai moi chat va khoi luong hao
     hut la SO LIEU PHAI NHAP tu nhat ky bao tri - he thong khong tu gia dinh.
   - Scope 2 (gian tiep): kWh that lay tu chi so cong to tich luy `energy_kwh_cumulative`, tinh
     delta giua cac mau ke tiep giong het `billing.py`, nhan he so luoi dien quoc gia.
   - Du lieu khong phu het ky bao cao thi noi ro phu bao bao nhieu %, KHONG bu dap bang cong suat
     gia dinh (ban cu lay 120 kW x 65% tai de dien vao cho du lieu thieu).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Equipment, TelemetrySample
from ..timeutil import utcnow

# He so phat thai luoi dien Viet Nam (MONRE / EVN Grid Emission Factor: tCO2 / MWh)
VIETNAM_GRID_EMISSION_FACTOR = 0.7221

# Global Warming Potential (GWP) theo IPCC AR5 / Montreal Protocol
GWP_FACTORS = {
    "R404A": 3922.0,  # 1 kg R404A thoat ra moi truong tuong duong 3,922 kg CO2
    "R134a": 1430.0,
    "R22": 1810.0,
    "NH3": 0.0,  # Amoniac tu nhien khong co GWP
}

HACCP_SEAFOOD_LIMIT_C = -18.0

#: Nguyen lieu dan xuat khoa ky chung chi, tach biet voi khoa JWT de lo mot khoa thi khoa kia
#: khong bi dung lai duoc (domain separation).
_CERT_KEY_INFO = b"thermalbiz-haccp-certificate-v1"


def _signing_key() -> bytes:
    return hmac.new(get_settings().jwt_secret_key.encode("utf-8"), _CERT_KEY_INFO, hashlib.sha256).digest()


def sign_certificate(facts: Dict[str, Any]) -> str:
    """HMAC-SHA256 tren cac so lieu kiem toan da chuan hoa.

    Day la tem chong gia mao (chi backend giu khoa moi tinh ra duoc), KHONG phai chu ky so theo
    nghia PKI: no chung to bao cao do backend nay lap va chua bi sua, nhung khong dung de chung
    minh tu cach phap ly cua don vi kiem toan. SHA-256 thuan (ban cu) ai cung tinh lai duoc nen
    khong co tac dung nay.
    """
    canonical = json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(_signing_key(), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def refrigerant_inventory(session: Session) -> Dict[str, int]:
    """So thiet bi dang hoat dong theo tung loai moi chat lanh, de nguoi nhap chon dung loai."""
    rows = session.execute(
        select(Equipment.refrigerant, func.count(Equipment.id))
        .where(Equipment.is_active.is_(True), Equipment.refrigerant.is_not(None))
        .group_by(Equipment.refrigerant)
    ).all()
    return {code: int(count) for code, count in rows}


def audited_equipment(session: Session, equipment_id: Optional[int] = None) -> List[Equipment]:
    """Thiet bi thuoc dien kiem toan HACCP: dang hoat dong VA co nguong HACCP da cau hinh."""
    query = select(Equipment).where(
        Equipment.is_active.is_(True),
        Equipment.haccp_limit_c.is_not(None),
    )
    if equipment_id is not None:
        query = query.where(Equipment.id == equipment_id)
    return list(session.scalars(query.order_by(Equipment.id)))


def audit_haccp_compliance(
    session: Session,
    equipment_id: Optional[int] = None,
    hours: int = 24,
) -> Dict[str, Any]:
    """Kiem toan an toan thuc pham chuoi lanh HACCP theo tieu chuan TCVN / Codex Alimentarius."""
    equipment_list = audited_equipment(session, equipment_id)

    now = utcnow()
    cutoff = now - timedelta(hours=hours)
    reports: List[Dict[str, Any]] = []
    total_measured = 0
    total_breaches = 0
    equipment_no_data = 0

    for eq in equipment_list:
        limit_c = eq.haccp_limit_c if eq.haccp_limit_c is not None else HACCP_SEAFOOD_LIMIT_C
        samples = list(
            session.scalars(
                select(TelemetrySample)
                .where((TelemetrySample.equipment_id == eq.id) & (TelemetrySample.ts >= cutoff))
                .order_by(TelemetrySample.ts.asc())
            )
        )

        temps = [s.temperature_c for s in samples if s.temperature_c is not None]
        breach_count = sum(1 for t in temps if t > limit_c)

        base = {
            "equipment_id": eq.id,
            "equipment_code": eq.code,
            "equipment_name": eq.name,
            "kind": eq.kind,
            "haccp_limit_c": limit_c,
            "sample_count": len(samples),
            "measured_count": len(temps),
            "missing_temperature_count": len(samples) - len(temps),
        }

        if not temps:
            equipment_no_data += 1
            reports.append({
                **base,
                "status": "NO_DATA",
                "verdict": "NO_DATA",
                "is_compliant": None,
                "compliance_pct": None,
                "breach_count": 0,
                "max_temp_c": None,
                "min_temp_c": None,
                "avg_temp_c": None,
            })
            continue

        total_measured += len(temps)
        total_breaches += breach_count

        is_compliant = breach_count == 0
        reports.append({
            **base,
            "status": "MONITORED",
            "is_compliant": is_compliant,
            # Mau so la so mau CO nhiet do: mau khong co nhiet do khong the tinh la tuan thu.
            "compliance_pct": round(((len(temps) - breach_count) / len(temps)) * 100.0, 2),
            "breach_count": breach_count,
            "max_temp_c": round(max(temps), 2),
            "min_temp_c": round(min(temps), 2),
            "avg_temp_c": round(sum(temps) / len(temps), 2),
            "verdict": "PASSED" if is_compliant else "CRITICAL_LIMIT_BREACHED",
        })

    # Khong the ket luan "dat" khi chua do duoc gi: DB rong hoac toan bo CCP mat ket noi deu cho
    # ra total_breaches == 0, va dieu do truoc day van phat hanh chung chi dat 100%.
    overall_compliance_pct: Optional[float]
    if total_measured == 0:
        overall_compliant = False
        overall_status = "NOT_VERIFIABLE"
        overall_note = (
            "Khong co mau nhiet do nao trong khung kiem toan de ket luan tuan thu. "
            "Khong the cap chung chi dat khi chua co du lieu do."
        )
        overall_compliance_pct = None
    else:
        overall_compliant = total_breaches == 0 and equipment_no_data == 0
        overall_status = "COMPLIANT" if overall_compliant else "NON_COMPLIANT"
        overall_note = (
            None
            if equipment_no_data == 0
            else f"{equipment_no_data} thiet bi CCP khong co du lieu nhiet do trong khung kiem toan."
        )
        overall_compliance_pct = round(((total_measured - total_breaches) / total_measured) * 100.0, 2)

    facts = {
        "audit_date": now.date().isoformat(),
        "window_hours": hours,
        "measured_samples": total_measured,
        "breaches": total_breaches,
        "equipment_no_data": equipment_no_data,
        "overall_compliant": overall_compliant,
        "per_equipment": [
            {"code": r["equipment_code"], "breaches": r["breach_count"], "measured": r["measured_count"]}
            for r in reports
        ],
    }
    cert_hash = sign_certificate(facts)

    return {
        "standard": "HACCP / TCVN 5603 (Codex Alimentarius) - nguong theo so CCP cua tung tai san",
        "seafood_frozen_limit_c": HACCP_SEAFOOD_LIMIT_C,
        "audit_window_hours": hours,
        "audit_window_start": cutoff.isoformat(),
        "audited_at": now.isoformat(),
        "overall_compliant": overall_compliant,
        "overall_status": overall_status,
        "overall_note": overall_note,
        "overall_compliance_pct": overall_compliance_pct,
        "audited_equipment_count": len(reports),
        "equipment_without_data_count": equipment_no_data,
        "total_monitored_samples": total_measured,
        "total_breaches": total_breaches,
        "certificate_id": f"CERT-HACCP-{cert_hash[:12].upper()}",
        "certificate_signature": cert_hash,
        "signature_scheme": "HMAC-SHA256",
        "equipment_audits": reports,
    }


def _measured_energy(session: Session, start: datetime, end: datetime) -> Dict[str, Any]:
    """Tong kWh that tu chi so cong to tich luy trong khoang [start, end].

    Tinh delta giua cac mau ke tiep cua TUNG thiet bi (giong `billing.py`): delta am nghia la cong
    to bi thay/reset giua ky thi bo qua khoang do va dem lai, khong am tham bu dap. Tra ve ca do
    dai thoi gian thuc su co du lieu de bao cao muc do phu song.
    """
    rows = session.execute(
        select(
            TelemetrySample.equipment_id,
            TelemetrySample.ts,
            TelemetrySample.energy_kwh_cumulative,
        )
        .where(
            TelemetrySample.ts >= start,
            TelemetrySample.ts <= end,
            TelemetrySample.energy_kwh_cumulative.is_not(None),
        )
        .order_by(TelemetrySample.equipment_id, TelemetrySample.ts)
    ).all()

    series: Dict[int, List[tuple]] = {}
    for equipment_id, ts, cumulative in rows:
        series.setdefault(equipment_id, []).append((ts, cumulative))

    total_kwh = 0.0
    covered_seconds = 0.0
    meter_reset_gaps = 0
    for points in series.values():
        if len(points) >= 2:
            covered_seconds = max(covered_seconds, (points[-1][0] - points[0][0]).total_seconds())
        for (_prev_ts, prev_cum), (_cur_ts, cur_cum) in zip(points, points[1:]):
            delta = cur_cum - prev_cum
            if delta < 0:
                meter_reset_gaps += 1
                continue
            total_kwh += delta

    return {
        "total_kwh": total_kwh,
        "covered_seconds": covered_seconds,
        "metered_equipment_count": len(series),
        "sample_count": len(rows),
        "meter_reset_gaps": meter_reset_gaps,
    }


def calculate_esg_carbon_footprint(
    session: Session,
    days: int = 30,
    refrigerant_leak_kg: float = 0.0,
    refrigerant_code: Optional[str] = None,
    ai_saving_scenario_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Tinh toan dau chan carbon ESG Scope 1 va Scope 2 cho toan bo he thong lanh & lo hoi.

    `refrigerant_code` va `refrigerant_leak_kg` phai la so lieu that tu nhat ky bao tri: khong co
    cam bien nao do duoc luong gas hao hut, va doi xe thiet bi dung nhieu loai moi chat khac nhau
    (R404A GWP 3922, R134a GWP 1430) nen khong the gia dinh mot loai.

    `ai_saving_scenario_pct` la KICH BAN gia dinh, khong phai so lieu do: khong truyen thi bao cao
    khong tinh phat thai tranh duoc, con hon la tu gan 12% roi trinh bay nhu that.
    """
    if refrigerant_leak_kg < 0:
        raise ValueError("Khoi luong moi chat hao hut khong the am")
    if refrigerant_code is None:
        # Chon mac dinh R404A o day thi moi loi goi thieu ma moi chat deu bi tinh theo GWP 3922,
        # du CHILLER_01 trong doi xe chay R134a. Thieu ma khi co hao hut -> bao loi, khong doan.
        if refrigerant_leak_kg > 0:
            raise ValueError(
                "Thieu refrigerant_code khi khoi luong hao hut > 0: "
                f"cac ma hop le {', '.join(sorted(GWP_FACTORS))}"
            )
        refrigerant_code = "KHONG_HAO_HUT"
        gwp = 0.0
    else:
        if refrigerant_code not in GWP_FACTORS:
            raise ValueError(
                f"Moi chat lanh '{refrigerant_code}' khong co he so GWP. Cac ma hop le: "
                f"{', '.join(sorted(GWP_FACTORS))}"
            )
        gwp = GWP_FACTORS[refrigerant_code]
    now = utcnow()
    cutoff = now - timedelta(days=days)

    energy = _measured_energy(session, cutoff, now)
    total_kwh = energy["total_kwh"]

    requested_seconds = float(days * 86400)
    coverage_pct = (
        round((energy["covered_seconds"] / requested_seconds) * 100.0, 2) if requested_seconds else 0.0
    )
    if energy["sample_count"] == 0:
        data_quality = "NO_METER_DATA"
    elif coverage_pct >= 95.0:
        data_quality = "MEASURED"
    else:
        data_quality = "PARTIAL"

    scope2_tco2e = (total_kwh * VIETNAM_GRID_EMISSION_FACTOR) / 1000.0
    scope1_refrigerant_tco2e = (refrigerant_leak_kg * gwp) / 1000.0
    total_tco2e = scope1_refrigerant_tco2e + scope2_tco2e

    ai_avoided_tco2e: Optional[float] = None
    ai_avoided_basis = "NOT_MODELLED"
    if ai_saving_scenario_pct is not None:
        ai_avoided_tco2e = round(
            ((total_kwh * ai_saving_scenario_pct / 100.0) * VIETNAM_GRID_EMISSION_FACTOR) / 1000.0, 3
        )
        ai_avoided_basis = "SCENARIO_PCT"

    return {
        "reporting_period_days": days,
        "grid_emission_factor_tco2_per_mwh": VIETNAM_GRID_EMISSION_FACTOR,
        "electricity_consumed_kwh": round(total_kwh, 2),
        "energy_data_quality": data_quality,
        "energy_coverage_pct": coverage_pct,
        "metered_equipment_count": energy["metered_equipment_count"],
        "meter_reset_gaps": energy["meter_reset_gaps"],
        "refrigerant_code": refrigerant_code,
        "refrigerant_loss_kg": round(refrigerant_leak_kg, 2),
        "refrigerant_gwp": gwp,
        "refrigerant_inventory": refrigerant_inventory(session),
        "scope_1_direct_tco2e": round(scope1_refrigerant_tco2e, 3),
        "scope_2_indirect_tco2e": round(scope2_tco2e, 3),
        "total_emissions_tco2e": round(total_tco2e, 3),
        "ai_avoided_emissions_tco2e": ai_avoided_tco2e,
        "ai_avoided_basis": ai_avoided_basis,
        "ai_saving_scenario_pct": ai_saving_scenario_pct,
        "carbon_intensity_kgco2e_per_kwh": (
            round((total_tco2e * 1000.0) / total_kwh, 4) if total_kwh > 0 else None
        ),
        "calculated_at": now.isoformat(),
        "methodology": (
            "GHG Protocol Corporate Standard; Scope 2 = kWh cong to tich luy x he so luoi VN; "
            "Scope 1 = khoi luong moi chat hao hut nhap tu nhat ky bao tri x GWP IPCC AR5"
        ),
    }

