"""Dich vu Dong bo Da chi nhanh Edge-to-Cloud (Multi-Site Sync Engine).

Xu ly dong bo Store-and-Forward tu cac nha may / kho lanh ve Cloud Command Center:
  1. Idempotency kiem tra truoc theo batch_id va hash noi dung.
  2. Nap TelemetrySample va Alert vao co so du lieu trung tam.
  3. Cap nhat trang thai suc khoe mang va do tre cua tung chi nhanh.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import Alert, Equipment, Metric, Severity, Site, SyncBatch, TelemetrySample
from ..timeutil import utcnow

logger = logging.getLogger("edge-sync")


def compute_batch_hash(site_code: str, batch_id: str, records: List[Dict[str, Any]]) -> str:
    content = f"{site_code}|{batch_id}|{json.dumps(records, sort_keys=True, ensure_ascii=False)}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def process_sync_batch(
    session: Session,
    site_code: str,
    batch_id: str,
    records: List[Dict[str, Any]],
    latency_ms: int = 45,
) -> Dict[str, Any]:
    batch_hash = compute_batch_hash(site_code, batch_id, records)

    # 1. Kiem tra Idempotency chong nap lap
    existing_batch = session.scalars(
        select(SyncBatch).where((SyncBatch.batch_id == batch_id) | (SyncBatch.idempotency_hash == batch_hash))
    ).first()
    if existing_batch:
        logger.info("Batch %s (hash %s) da duoc xu ly truoc do. Bo qua.", batch_id, batch_hash[:8])
        return {
            "status": "already_synced",
            "batch_id": batch_id,
            "processed": existing_batch.records_count,
            "message": "Batch already processed by idempotency check",
        }

    # 2. Tim hoac tao Site
    site = session.scalars(select(Site).where(Site.code == site_code)).first()
    if not site:
        site = Site(
            code=site_code,
            name=f"Chi nhánh {site_code}",
            location="Khu công nghiệp / Kho vệ tinh",
            is_active=True,
            sync_status="ONLINE",
            sync_latency_ms=latency_ms,
            created_at=utcnow(),
        )
        session.add(site)
        session.flush()

    # 3. Nap tung ban ghi telemetry tu Edge
    processed_count = 0
    equipment_cache: Dict[str, Equipment] = {}
    seen_equipment_ts: set[tuple[int, datetime]] = set()

    for item in records:
        rtype = item.get("type", "telemetry")
        if rtype == "telemetry":
            eq_code = item.get("equipment_code")
            if not eq_code:
                continue
            if eq_code not in equipment_cache:
                eq = session.scalars(select(Equipment).where(Equipment.code == eq_code)).first()
                if not eq:
                    eq = Equipment(
                        code=eq_code,
                        name=f"Thiết bị {eq_code} ({site.name})",
                        kind="DEEP_FREEZER",
                        location=site.name,
                        rated_power_kw=50.0,
                        is_active=True,
                    )
                    session.add(eq)
                    session.flush()
                equipment_cache[eq_code] = eq

            eq = equipment_cache.get(eq_code)
            if not eq:
                continue

            ts_raw = item.get("timestamp") or item.get("ts")
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(str(ts_raw))
                except Exception:
                    ts = utcnow()
            else:
                ts = utcnow()

            # Tranh xung dot UniqueConstraint(equipment_id, ts) khi nhieu ban ghi den cung luc
            while (eq.id, ts) in seen_equipment_ts:
                ts = ts + timedelta(microseconds=1000)
            seen_equipment_ts.add((eq.id, ts))

            sample = TelemetrySample(
                equipment_id=eq.id,
                ts=ts,
                temperature_c=item.get("temperature_c"),
                pressure_bar=item.get("pressure_bar"),
                power_kw=item.get("power_kw"),
                cooling_capacity_kw=item.get("cooling_capacity_kw"),
                cop=item.get("cop"),
                efficiency_pct=item.get("efficiency_pct"),
                vibration_mm_s=item.get("vibration_mm_s"),
                energy_kwh_cumulative=item.get("energy_kwh_cumulative"),
                status=item.get("status", "RUNNING"),
            )
            session.add(sample)
            processed_count += 1

    # 4. Cap nhat thong tin Site
    site.last_sync_at = utcnow()
    site.sync_status = "ONLINE"
    site.sync_latency_ms = latency_ms
    site.pending_records_count = max(0, site.pending_records_count - processed_count)

    # 5. Luu SyncBatch
    sync_batch = SyncBatch(
        batch_id=batch_id,
        site_id=site.id,
        site_code=site_code,
        received_at=utcnow(),
        records_count=processed_count,
        status="PROCESSED",
        idempotency_hash=batch_hash,
    )
    session.add(sync_batch)
    session.commit()

    logger.info("Dong bo thanh cong %d ban ghi tu %s (Batch %s)", processed_count, site_code, batch_id)
    return {
        "status": "ok",
        "batch_id": batch_id,
        "site_code": site_code,
        "processed": processed_count,
        "server_time": utcnow().isoformat(),
    }


def list_sites_with_health(session: Session) -> List[Dict[str, Any]]:
    sites = list(session.scalars(select(Site).order_by(Site.code.asc())))
    now = utcnow()
    results = []

    for s in sites:
        # Neu qua 5 phut chua sync -> coi la OFFLINE / MAT KET NOI
        is_stale = s.last_sync_at is None or (now - s.last_sync_at) > timedelta(minutes=5)
        live_status = "OFFLINE" if is_stale else s.sync_status
        results.append({
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "location": s.location,
            "is_active": s.is_active,
            "status": live_status,
            "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
            "latency_ms": s.sync_latency_ms if not is_stale else None,
            "pending_records": s.pending_records_count,
        })
    return results
