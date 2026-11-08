"""Bo kiem thu Pillar 3: Multi-Site Edge-to-Cloud Sync Engine.

Kiem chung:
  1. Xac thuc bao mat tren POST /api/sync/push bang X-Connector-Api-Key.
  2. Tinh Idempotency: khong nap lap du lieu khi mang gui lai batch cu.
  3. Quan ly suc khoe Site (ONLINE vs OFFLINE khi stale qua 5 phut, do tre ms).
  4. Lich su SyncBatch va thong ke toan mang /api/sync/status.
  5. Tich hop EdgeSyncAgent voi local SQLite outbox queue.
"""

from __future__ import annotations

import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models import Equipment, Site, SyncBatch, TelemetrySample
from app.timeutil import utcnow


@pytest.fixture
def connector_headers() -> dict[str, str]:
    return {"X-Connector-Api-Key": "test-connector-api-key"}


def test_sync_push_requires_api_key(client: TestClient):
    payload = {
        "site_code": "SITE-TEST-01",
        "batch_id": "BATCH-001",
        "records": [],
    }
    # Thieu header
    res = client.post("/api/sync/push", json=payload)
    assert res.status_code == 401

    # Sai header
    res = client.post("/api/sync/push", json=payload, headers={"X-Connector-Api-Key": "wrong-key"})
    assert res.status_code == 401


def test_sync_push_requires_registered_site(seeded_client: TestClient, connector_headers: dict[str, str]):
    """Site la master data. Edge khong duoc tu sinh ra chi nhanh bang cach day du lieu len."""
    res = seeded_client.post(
        "/api/sync/push",
        json={
            "site_code": f"SITE-GIA-{uuid.uuid4().hex[:6]}",
            "batch_id": f"BATCH-{uuid.uuid4().hex[:8]}",
            "records": [],
        },
        headers=connector_headers,
    )
    assert res.status_code == 404
    assert "chua duoc dang ky" in res.json()["detail"]


def test_sync_push_ingests_telemetry_and_records_batch(seeded_client: TestClient, connector_headers: dict[str, str]):
    batch_id = f"BATCH-{uuid.uuid4().hex[:8]}"
    site_code = "SITE-NHA-A"

    payload = {
        "site_code": site_code,
        "batch_id": batch_id,
        "latency_ms": 32,
        "records": [
            {
                "type": "telemetry",
                "equipment_code": "KHO_DONG_01",
                "temperature_c": -18.5,
                "pressure_bar": 12.4,
                "power_kw": 45.2,
                "cop": 3.42,
                "efficiency_pct": 88.5,
                "vibration_mm_s": 1.8,
                "status": "RUNNING",
                "timestamp": utcnow().isoformat(),
            }
        ],
    }

    res = seeded_client.post("/api/sync/push", json=payload, headers=connector_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["batch_id"] == batch_id
    assert data["processed"] == 1
    assert data["rejected"] == []

    # Kiem tra trong DB
    session: Session = SessionLocal()
    try:
        saved_site = session.scalars(select(Site).where(Site.code == site_code)).first()
        assert saved_site is not None
        assert saved_site.sync_status == "ONLINE"
        assert saved_site.sync_latency_ms == 32

        saved_batch = session.scalars(select(SyncBatch).where(SyncBatch.batch_id == batch_id)).first()
        assert saved_batch is not None
        assert saved_batch.site_code == site_code
        assert saved_batch.records_count == 1

        # COP client tu khai (3.42) phai bi bo: Cloud tinh lai tu Q_o / N_e.
        # Mau nay khong co cooling_capacity_kw nen COP that su la "khong xac dinh duoc".
        # Tuong tu, hieu suat dot chi danh cho lo hoi - kho dong khong duoc ghi.
        equipment = session.scalars(select(Equipment).where(Equipment.code == "KHO_DONG_01")).first()
        assert equipment is not None
        saved_sample = session.scalars(
            select(TelemetrySample)
            .where(TelemetrySample.equipment_id == equipment.id)
            .order_by(TelemetrySample.ts.desc())
            .limit(1)
        ).first()
        assert saved_sample is not None
        assert saved_sample.cop is None
        assert saved_sample.efficiency_pct is None
        assert saved_sample.temperature_c == -18.5
    finally:
        session.close()


def test_sync_push_rejects_unregistered_equipment_with_reason(
    seeded_client: TestClient, connector_headers: dict[str, str]
):
    """Ban ghi bi tu choi phai tra ve kem ly do, khong duoc bo qua trong im lang."""
    batch_id = f"BATCH-{uuid.uuid4().hex[:8]}"
    res = seeded_client.post(
        "/api/sync/push",
        json={
            "site_code": "SITE-NHA-B",
            "batch_id": batch_id,
            "records": [
                {"type": "telemetry", "equipment_code": "MAY_LA", "temperature_c": -10.0,
                 "timestamp": utcnow().isoformat()},
                {"type": "telemetry", "equipment_code": "KHO_DONG_01", "temperature_c": -19.0,
                 "timestamp": utcnow().isoformat()},
            ],
        },
        headers=connector_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["processed"] == 1
    assert len(data["rejected"]) == 1
    assert data["rejected"][0]["index"] == 0
    assert data["rejected"][0]["equipment_code"] == "MAY_LA"
    assert "chua duoc dang ky" in data["rejected"][0]["error"]


def test_sync_push_skips_duplicate_sample_across_batches(
    seeded_client: TestClient, connector_headers: dict[str, str]
):
    """Trung (equipment_id, ts) xuyen batch -> bo qua, khong doi ts de lach UniqueConstraint."""
    moment = utcnow().isoformat()
    record = {"type": "telemetry", "equipment_code": "KHO_DONG_01", "temperature_c": -19.0, "timestamp": moment}

    first = seeded_client.post(
        "/api/sync/push",
        json={"site_code": "SITE-NHA-C", "batch_id": f"BATCH-{uuid.uuid4().hex[:8]}", "records": [record]},
        headers=connector_headers,
    )
    assert first.json()["processed"] == 1

    second = seeded_client.post(
        "/api/sync/push",
        json={"site_code": "SITE-NHA-C", "batch_id": f"BATCH-{uuid.uuid4().hex[:8]}", "records": [record]},
        headers=connector_headers,
    )
    body = second.json()
    assert second.status_code == 200
    assert body["processed"] == 0
    assert body["duplicates_skipped"] == 1


def test_sync_idempotency_prevents_duplicate_processing(seeded_client: TestClient, connector_headers: dict[str, str]):
    batch_id = f"BATCH-DUP-{uuid.uuid4().hex[:8]}"
    site_code = "SITE-NHA-A"

    payload = {
        "site_code": site_code,
        "batch_id": batch_id,
        "latency_ms": 25,
        "records": [
            {
                "type": "telemetry",
                "equipment_code": "KHO_DONG_01",
                "temperature_c": -20.1,
                "timestamp": utcnow().isoformat(),
            }
        ],
    }

    # Lan 1: thanh cong
    res1 = seeded_client.post("/api/sync/push", json=payload, headers=connector_headers)
    assert res1.status_code == 200
    assert res1.json()["status"] == "ok"

    # Lan 2: gui trung batch -> tra ve already_synced
    res2 = seeded_client.post("/api/sync/push", json=payload, headers=connector_headers)
    assert res2.status_code == 200
    assert res2.json()["status"] == "already_synced"
    assert "idempotency" in res2.json()["message"].lower()


def test_sync_sites_health_and_offline_detection(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}
    session: Session = SessionLocal()
    stale_site_code = f"SITE-STALE-{uuid.uuid4().hex[:4]}"
    fresh_site_code = f"SITE-FRESH-{uuid.uuid4().hex[:4]}"
    try:
        # Tao mot site mat ket noi 10 phut truoc
        stale_site = Site(
            code=stale_site_code,
            name="Kho Stale",
            location="Vung xa",
            is_active=True,
            sync_status="ONLINE",
            last_sync_at=utcnow() - timedelta(minutes=10),
            sync_latency_ms=120,
        )
        fresh_site = Site(
            code=fresh_site_code,
            name="Kho Fresh",
            location="Ha Noi",
            is_active=True,
            sync_status="ONLINE",
            last_sync_at=utcnow() - timedelta(minutes=1),
            sync_latency_ms=15,
        )
        session.add_all([stale_site, fresh_site])
        session.commit()
    finally:
        session.close()

    res = seeded_client.get("/api/sync/sites", headers=headers)
    assert res.status_code == 200
    sites = res.json()
    stale_entry = next((s for s in sites if s["code"] == stale_site_code), None)
    fresh_entry = next((s for s in sites if s["code"] == fresh_site_code), None)

    assert stale_entry is not None
    assert stale_entry["status"] == "OFFLINE"  # Tu dong nhan dien mat ket noi vi > 5 phut

    assert fresh_entry is not None
    assert fresh_entry["status"] == "ONLINE"
    assert fresh_entry["latency_ms"] == 15


def test_sync_network_status_overview(seeded_client: TestClient, tokens: dict[str, str]):
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}
    res = seeded_client.get("/api/sync/status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_sites" in data
    assert "online_sites" in data
    assert "offline_sites" in data
    assert "total_batches_synced" in data
    assert "total_records_ingested" in data


def test_edge_sync_agent_outbox_queue_integration(seeded_client: TestClient, monkeypatch, tmp_path: Path):
    """Kiem tra EdgeSyncAgent voi SQLite outbox cuc bo va flush len TestClient."""
    from clients.edge_sync_agent.edge_agent import EdgeSyncAgent

    db_path = tmp_path / "test_outbox.db"
    agent = EdgeSyncAgent(
        site_code="SITE-NHA-A",
        cloud_url="http://testserver",
        api_key="test-connector-api-key",
        db_path=db_path,
    )

    # Enqueue 3 ban ghi voi timestamp thuc te
    t_now = utcnow()
    agent.enqueue_record({"equipment_code": "KHO_DONG_01", "temperature_c": -19.0, "ts": (t_now - timedelta(minutes=2)).isoformat()})
    agent.enqueue_record({"equipment_code": "KHO_DONG_02", "temperature_c": -18.2, "ts": (t_now - timedelta(minutes=1)).isoformat()})
    agent.enqueue_record({"equipment_code": "KHO_DONG_01", "temperature_c": -19.5, "ts": t_now.isoformat()})

    stats = agent.get_stats()
    assert stats["pending_count"] == 3
    assert stats["synced_count"] == 0

    # Mock requests.post de goi truc tiep TestClient
    def mock_post(url, json=None, headers=None, timeout=None):
        class MockResponse:
            def __init__(self, resp):
                self.status_code = resp.status_code
                self._json = resp.json()
                self.text = resp.text
            def json(self):
                return self._json

        resp = seeded_client.post("/api/sync/push", json=json, headers=headers)
        return MockResponse(resp)

    monkeypatch.setattr("requests.post", mock_post)

    flush_result = agent.flush_batch()
    assert flush_result["status"] == "success"
    assert flush_result["flushed"] == 3

    stats_after = agent.get_stats()
    assert stats_after["pending_count"] == 0
    assert stats_after["synced_count"] == 3

    # Lan flush dau tien chua tung do duoc do tre nao, nen KHONG duoc bao ve Cloud
    # mot con so 0ms/45ms gia mao. Cloud giu nguyen gia tri cu (0 = "chua tung do").
    session: Session = SessionLocal()
    try:
        site = session.scalars(select(Site).where(Site.code == "SITE-NHA-A")).first()
        assert site is not None
        assert site.sync_status == "ONLINE"
        assert site.last_sync_at is not None
        assert site.sync_latency_ms == 0
        # Outbox that su rong -> pending_records_count ve 0, khong phai gia dinh.
        assert site.pending_records_count == 0
    finally:
        session.close()


def test_edge_sync_agent_keeps_rejected_rows_pending(seeded_client: TestClient, monkeypatch, tmp_path: Path):
    """Cloud tu choi ban ghi nao thi Edge phai giu ban ghi do de gui lai.

    Neu danh dau synced cho ban ghi bi tu choi, du lieu mat vinh vien o bien
    va khong con dau hieu nao de phat hien.
    """
    from clients.edge_sync_agent.edge_agent import EdgeSyncAgent

    agent = EdgeSyncAgent(
        site_code="SITE-NHA-B",
        cloud_url="http://testserver",
        api_key="test-connector-api-key",
        db_path=tmp_path / "test_outbox_reject.db",
    )
    t_now = utcnow()
    agent.enqueue_record({"equipment_code": "KHO_DONG_01", "temperature_c": -19.0, "ts": t_now.isoformat()})
    agent.enqueue_record({"equipment_code": "MAY_KHONG_CO_THAT", "temperature_c": -10.0, "ts": t_now.isoformat()})

    def mock_post(url, json=None, headers=None, timeout=None):
        class MockResponse:
            def __init__(self, resp):
                self.status_code = resp.status_code
                self._json = resp.json()
                self.text = resp.text

            def json(self):
                return self._json

        return MockResponse(seeded_client.post("/api/sync/push", json=json, headers=headers))

    monkeypatch.setattr("requests.post", mock_post)

    flush_result = agent.flush_batch()
    assert flush_result["status"] == "partial"
    assert flush_result["flushed"] == 1
    assert flush_result["rejected"] == 1

    stats = agent.get_stats()
    assert stats["synced_count"] == 1
    assert stats["pending_count"] == 1
