"""Dich vu Dong bo Da chi nhanh Edge-to-Cloud (Multi-Site Sync Engine).

Xu ly dong bo Store-and-Forward tu cac nha may / kho lanh ve Cloud Command Center.
Bon nguyen tac nghiep vu:
  1. Chi nhan du lieu cua thiet bi VA chi nhanh DA DANG KY. Edge khong duoc tu sinh ra
     tai san: ban cu tu tao Site va Equipment voi kind / cong suat gia dinh, va nhung
     gia dinh do chay thang vao bao cao nang luong va hoa don.
  2. COP LUON tinh lai tu Q_o / N_e o Cloud, giong het /api/ingest. Client khai COP -> bo.
  3. Canh bao do AlarmRule phia server quyet dinh. Edge co khai type="alert" thi van
     phai di qua thermal.evaluate_sample; khong bao gio tin canh bao do client tu cong bo.
  4. Ban ghi bi tu choi phai tra ve kem ly do. Im lang bo roi la mat du lieu ma khong
     ai biet de sua.

Idempotency: trung batch_id HOAC trung hash noi dung -> khong nap lai. Trung
(equipment_id, ts) xuyen batch -> bo qua ban ghi do. KHONG doi ts di 1ms de "lach"
UniqueConstraint: viec do lam sai thoi diem do thuc te va sai ca tich phan kWh.

`latency_ms` va `pending_records` la so do phia Edge. Thieu thi giu nguyen gia tri cu,
khong duoc suy ra 0 hay 45 roi hien thi nhu the la so that.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Equipment, Site, SyncBatch, TelemetrySample
from ..timeutil import utcnow
from . import thermal

logger = logging.getLogger("edge-sync")

#: Edge chi duoc day hai loai ban ghi nay. Loai khac -> tu choi kem ly do, khong bo qua im lang.
SUPPORTED_RECORD_TYPES: Tuple[str, ...] = ("telemetry", "alert")

#: Qua moc nay chua thay goi sync nao thi coi chi nhanh mat ket noi.
SITE_STALE_AFTER = timedelta(minutes=5)


class UnknownSiteError(Exception):
    """Edge day du lieu len mot site_code chua duoc dang ky o Cloud."""

    def __init__(self, site_code: str) -> None:
        self.site_code = site_code
        self.message = (
            f"Chi nhanh '{site_code}' chua duoc dang ky trong he thong. "
            f"Cloud khong tu tao Site tu du lieu Edge gui len."
        )
        super().__init__(self.message)


def compute_batch_hash(site_code: str, batch_id: str, records: List[Dict[str, Any]]) -> str:
    content = f"{site_code}|{batch_id}|{json.dumps(records, sort_keys=True, ensure_ascii=False)}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_edge_timestamp(raw: Any) -> Optional[datetime]:
    """Doi timestamp cua Edge ve naive-UTC. Tra ve None khi thieu hoac sai dinh dang.

    Edge agent gui ISO kem '+00:00' (aware) trong khi cot DateTime o day la naive-UTC
    (xem timeutil.py). Khong chuan hoa thi so sanh aware/naive se TypeError -> 500 ->
    Edge retry mai mai. KHONG duoc "chua chay" ve utcnow(): gan thoi diem hien tai cho
    mot mau cu bien du lieu cu thanh du lieu moi va che mat su co mat ket noi.
    """
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _reject(index: int, item: Dict[str, Any], error: str) -> Dict[str, Any]:
    return {"index": index, "equipment_code": item.get("equipment_code"), "error": error}


def _load_equipment(session: Session, codes: Iterable[Any]) -> Dict[str, Equipment]:
    clean = {str(code).strip() for code in codes if code}
    if not clean:
        return {}
    rows = session.scalars(select(Equipment).where(Equipment.code.in_(clean)))
    return {e.code: e for e in rows}


def _existing_sample_keys(session: Session, pairs: Set[Tuple[int, datetime]]) -> Set[Tuple[int, datetime]]:
    """Cac (equipment_id, ts) DA CO trong DB, de phat hien trung lap xuyen batch.

    Loc theo dung khoang [min, max] cua chinh batch nay thay vi quet toan bang.
    """
    if not pairs:
        return set()
    stamps = [ts for _, ts in pairs]
    rows = session.execute(
        select(TelemetrySample.equipment_id, TelemetrySample.ts).where(
            TelemetrySample.equipment_id.in_({equipment_id for equipment_id, _ in pairs}),
            TelemetrySample.ts >= min(stamps),
            TelemetrySample.ts <= max(stamps),
        )
    ).all()
    return {(row[0], row[1]) for row in rows}


def process_sync_batch(
    session: Session,
    site_code: str,
    batch_id: str,
    records: List[Dict[str, Any]],
    latency_ms: Optional[int] = None,
    pending_records: Optional[int] = None,
) -> Dict[str, Any]:
    """Nap mot goi Store-and-Forward tu Edge len Cloud.

    Raises:
        UnknownSiteError: site_code chua duoc dang ky. Tu tao Site o day nghia la bat ky
            ai co CONNECTOR_API_KEY cung co the them chi nhanh gia vao bao cao mang.
    """
    batch_hash = compute_batch_hash(site_code, batch_id, records)

    # 1. Kiem tra Idempotency chong nap lap (trung batch_id HOAC trung hash noi dung)
    existing_batch = session.scalars(
        select(SyncBatch).where((SyncBatch.batch_id == batch_id) | (SyncBatch.idempotency_hash == batch_hash))
    ).first()
    if existing_batch:
        logger.info("Batch %s (hash %s) da duoc xu ly truoc do. Bo qua.", batch_id, batch_hash[:8])
        return {
            "status": "already_synced",
            "batch_id": batch_id,
            "site_code": site_code,
            "processed": existing_batch.records_count,
            "duplicates_skipped": 0,
            "rejected": [],
            "alerts_raised": [],
            "message": "Batch already processed by idempotency check",
        }

    # 2. Site phai duoc dang ky truoc. Khong tu sinh ra tu du lieu client.
    site = session.scalars(select(Site).where(Site.code == site_code)).first()
    if site is None:
        raise UnknownSiteError(site_code)

    # 3. Phan loai ban ghi TRUOC khi ghi, giong /api/ingest/telemetry/batch: mot lan
    #    rollback se keo theo tat ca mau da luu va bien so `processed` thanh noi doi.
    equipment_by_code = _load_equipment(session, [item.get("equipment_code") for item in records])

    staged: List[Tuple[Dict[str, Any], Equipment, datetime]] = []
    rejected: List[Dict[str, Any]] = []
    for index, item in enumerate(records):
        record_type = str(item.get("type") or "telemetry")
        if record_type not in SUPPORTED_RECORD_TYPES:
            rejected.append(
                _reject(
                    index,
                    item,
                    f"Loai ban ghi '{record_type}' khong duoc ho tro. "
                    f"Cac loai hop le: {', '.join(SUPPORTED_RECORD_TYPES)}.",
                )
            )
            continue

        code = item.get("equipment_code")
        if not code:
            rejected.append(_reject(index, item, "Thieu 'equipment_code'."))
            continue

        equipment = equipment_by_code.get(str(code).strip())
        if equipment is None:
            rejected.append(_reject(index, item, f"Thiet bi '{code}' chua duoc dang ky trong he thong."))
            continue

        ts = parse_edge_timestamp(item.get("timestamp") or item.get("ts"))
        if ts is None:
            rejected.append(
                _reject(index, item, "Thieu hoac sai dinh dang 'timestamp' (can ISO-8601, vi du 2026-11-08T01:00:00Z).")
            )
            continue

        staged.append((item, equipment, ts))

    # 4. Loc trung lap: trong cung batch va xuyen batch (Edge day lai goi cu).
    seen: Set[Tuple[int, datetime]] = set()
    unique_staged: List[Tuple[Dict[str, Any], Equipment, datetime]] = []
    duplicates = 0
    for item, equipment, ts in staged:
        key = (equipment.id, ts)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique_staged.append((item, equipment, ts))

    already_stored = _existing_sample_keys(session, seen)

    # 5. Ghi mau va cham diem canh bao. COP do Cloud tinh lai, alert do AlarmRule quyet dinh.
    all_alerts: List[Any] = []
    processed = 0
    for item, equipment, ts in unique_staged:
        if (equipment.id, ts) in already_stored:
            duplicates += 1
            continue

        power_kw = item.get("power_kw")
        cooling_capacity_kw = item.get("cooling_capacity_kw")
        sample = TelemetrySample(
            equipment_id=equipment.id,
            ts=ts,
            temperature_c=item.get("temperature_c"),
            pressure_bar=item.get("pressure_bar"),
            power_kw=power_kw,
            cooling_capacity_kw=cooling_capacity_kw if equipment.is_refrigeration else None,
            cop=thermal.compute_cop(cooling_capacity_kw, power_kw) if equipment.is_refrigeration else None,
            efficiency_pct=item.get("efficiency_pct") if equipment.is_combustion else None,
            vibration_mm_s=item.get("vibration_mm_s"),
            energy_kwh_cumulative=item.get("energy_kwh_cumulative"),
            status=item.get("status"),
        )
        session.add(sample)
        session.flush()
        all_alerts.extend(thermal.evaluate_sample(session, equipment, sample))
        processed += 1

    # 6. Cap nhat suc khoe Site. Chi ghi khi Edge thuc su do va bao len.
    site.last_sync_at = utcnow()
    site.sync_status = "ONLINE"
    if latency_ms is not None:
        site.sync_latency_ms = latency_ms
    if pending_records is not None:
        site.pending_records_count = max(0, pending_records - processed)

    # 7. Luu SyncBatch. PARTIAL khi co ban ghi bi tu choi de con dau vet ma dieu tra.
    session.add(
        SyncBatch(
            batch_id=batch_id,
            site_id=site.id,
            site_code=site_code,
            received_at=utcnow(),
            records_count=processed,
            status="PARTIAL" if rejected else "PROCESSED",
            idempotency_hash=batch_hash,
        )
    )
    session.commit()

    logger.info(
        "Dong bo %d ban ghi tu %s (Batch %s), bo qua %d ban trung, tu choi %d ban.",
        processed,
        site_code,
        batch_id,
        duplicates,
        len(rejected),
    )
    return {
        "status": "ok",
        "batch_id": batch_id,
        "site_code": site_code,
        "processed": processed,
        "duplicates_skipped": duplicates,
        "rejected": rejected,
        "alerts_raised": [thermal.serialize_alert(a) for a in all_alerts],
        "server_time": utcnow().isoformat(),
    }


def list_sites_with_health(session: Session) -> List[Dict[str, Any]]:
    sites = list(session.scalars(select(Site).order_by(Site.code.asc())))
    now = utcnow()
    results = []

    for s in sites:
        is_stale = s.last_sync_at is None or (now - s.last_sync_at) > SITE_STALE_AFTER
        live_status = "OFFLINE" if is_stale else s.sync_status
        # Cot sync_latency_ms NOT NULL default 0, nen 0 nghia la "chua tung do",
        # khong phai "do tre 0 ms". Hien 0 ra UI la noi doi ve chat luong mang.
        measured_latency = s.sync_latency_ms if (not is_stale and s.sync_latency_ms > 0) else None
        results.append({
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "location": s.location,
            "is_active": s.is_active,
            "status": live_status,
            "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
            "latency_ms": measured_latency,
            "pending_records": s.pending_records_count,
        })
    return results
