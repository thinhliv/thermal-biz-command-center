"""Edge Store-and-Forward Sync Agent.

Chay tai cac kho lanh ve tinh / chi nhanh (satellite sites) de thu thap
telemetry va alerts tu cam bien cuc bo, luu vao SQLite outbox va dong bo ve Cloud.

Chong mat du lieu khi dut cap mang:
  - Khi mat ket noi Internet, du lieu van ghi deu dan vao `outbox.db`.
  - Khi mang phuc hoi, Agent tu dong flush cac batch con ton dong len Cloud.
  - Ho tro Idempotency, retry backoff, va bao cao do tre (latency).
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [EdgeAgent] %(message)s")
logger = logging.getLogger("EdgeAgent")


def utcnow_str() -> str:
    return datetime.now(timezone.utc).isoformat()


class EdgeSyncAgent:
    """Agent dong bo Store-and-Forward tai bien chi nhanh."""

    def __init__(
        self,
        site_code: str,
        cloud_url: str,
        api_key: str,
        db_path: str | Path = "edge_outbox.db",
        timeout_seconds: int = 10,
    ) -> None:
        self.site_code = site_code
        self.cloud_url = cloud_url.rstrip("/")
        self.api_key = api_key
        self.db_path = str(db_path)
        self.timeout_seconds = timeout_seconds
        #: Do tre cua LAN flush truoc. Chi co sau khi thuc su goi Cloud mot lan,
        #: nen goi dau tien khong gui latency (hon la bao 0ms - mot con so khong co that).
        self._last_latency_ms: Optional[int] = None
        self._init_db()

    @staticmethod
    def _mark_synced(conn: sqlite3.Connection, ids: List[int], batch_id: str) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"""
            UPDATE outbox
            SET synced = 1, batch_id = ?, synced_at = ?, retry_count = 0, last_error = NULL
            WHERE id IN ({placeholders})
            """,
            [batch_id, utcnow_str()] + list(ids),
        )
        conn.commit()

    @staticmethod
    def _mark_failed(conn: sqlite3.Connection, ids: List[int], error: str) -> None:
        """Giu ban ghi o trang thai CHUA sync de lan sau gui lai.

        Khong bao gio danh dau synced cho mot ban ghi Cloud tu choi: viec do bien
        "mat du lieu" thanh "da dong bo xong" va khong con cach nao phat hien ra.
        """
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"""
            UPDATE outbox
            SET retry_count = retry_count + 1, last_error = ?
            WHERE id IN ({placeholders})
            """,
            [error] + list(ids),
        )
        conn.commit()

    @staticmethod
    def _rejected_row_ids(cloud_response: Dict[str, Any], row_ids: List[int]) -> Dict[int, str]:
        """Map row_id -> ly do tu choi, doc tu field `rejected` ma Cloud tra ve.

        Cloud danh `index` theo vi tri trong mang `records` da gui, nen phai doi qua
        `row_ids` theo dung thu tu do. Thieu buoc nay thi mot ban ghi bi tu choi van
        bi danh dau synced va mat vinh vien o bien.
        """
        result: Dict[int, str] = {}
        for item in cloud_response.get("rejected") or []:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if not isinstance(index, int) or not 0 <= index < len(row_ids):
                continue
            result[row_ids[index]] = str(item.get("error") or "Cloud tu choi ban ghi")
        return result

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_code TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    synced INTEGER NOT NULL DEFAULT 0,
                    batch_id TEXT,
                    synced_at TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_synced ON outbox (synced, id)"
            )
            conn.commit()

    def enqueue_record(self, record: Dict[str, Any], record_type: str = "telemetry") -> int:
        """Ghi mot ban ghi telemetry hoac alert vao outbox cuc bo."""
        payload_str = json.dumps(record, ensure_ascii=False)
        now_ts = utcnow_str()
        with self._connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO outbox (site_code, record_type, payload, created_at, synced)
                VALUES (?, ?, ?, ?, 0)
                """,
                (self.site_code, record_type, payload_str, now_ts),
            )
            conn.commit()
            return cur.lastrowid

    def get_stats(self) -> Dict[str, Any]:
        """Thong ke tinh trang hang doi outbox."""
        with self._connection() as conn:
            pending = conn.execute("SELECT COUNT(*) FROM outbox WHERE synced = 0").fetchone()[0]
            synced = conn.execute("SELECT COUNT(*) FROM outbox WHERE synced = 1").fetchone()[0]
            oldest = conn.execute("SELECT MIN(created_at) FROM outbox WHERE synced = 0").fetchone()[0]
            return {
                "site_code": self.site_code,
                "pending_count": pending,
                "synced_count": synced,
                "oldest_pending": oldest,
                "db_path": self.db_path,
            }

    def flush_batch(self, batch_size: int = 100) -> Dict[str, Any]:
        """Lay cac ban ghi chua sync, goi batch len Cloud va danh dau hoan tat."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT id, record_type, payload FROM outbox
                WHERE synced = 0
                ORDER BY id ASC
                LIMIT ?
                """,
                (batch_size,),
            ).fetchall()

            if not rows:
                return {"status": "empty", "flushed": 0, "pending": 0}

            row_ids: List[int] = []
            records: List[Dict[str, Any]] = []
            corrupt_ids: List[int] = []
            for r in rows:
                try:
                    parsed = json.loads(r["payload"])
                except Exception as exc:
                    corrupt_ids.append(r["id"])
                    logger.error("Row outbox id=%s hong JSON, khong the dong bo: %s", r["id"], exc)
                    continue
                parsed["type"] = r["record_type"]
                row_ids.append(r["id"])
                records.append(parsed)

            # Row hong la du lieu khong the phuc hoi: giu nguyen synced = 0 de --stats
            # con nhin thay, va ghi last_error thay vi "bo qua" trong im lang.
            self._mark_failed(conn, corrupt_ids, "CORRUPT_PAYLOAD: khong doc duoc JSON cuc bo")

            if not records:
                return {
                    "status": "no_sendable_records",
                    "flushed": 0,
                    "corrupt_records": len(corrupt_ids),
                    "pending": len(rows) - len(corrupt_ids),
                }

            batch_id = f"BATCH-{self.site_code}-{uuid.uuid4().hex[:12].upper()}"

            url = f"{self.cloud_url}/api/sync/push"
            headers = {
                "X-Connector-Api-Key": self.api_key,
                "Content-Type": "application/json",
            }
            body: Dict[str, Any] = {
                "site_code": self.site_code,
                "batch_id": batch_id,
                # So ban ghi con ton trong outbox TRUOC goi nay (tinh ca chinh goi nay).
                # Chi Edge moi biet con so nay; Cloud tru di so da nap de hien thi hang doi.
                "pending_records": conn.execute(
                    "SELECT COUNT(*) FROM outbox WHERE synced = 0"
                ).fetchone()[0],
                "records": records,
            }
            if self._last_latency_ms is not None:
                body["latency_ms"] = self._last_latency_ms

            try:
                t0 = time.perf_counter()
                resp = requests.post(url, json=body, headers=headers, timeout=self.timeout_seconds)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._last_latency_ms = latency_ms

                if resp.status_code in (200, 201):
                    data = resp.json()
                    errors_by_id = self._rejected_row_ids(data, row_ids)
                    rejected_ids = list(errors_by_id)
                    accepted_ids = [rid for rid in row_ids if rid not in errors_by_id]

                    self._mark_synced(conn, accepted_ids, batch_id)
                    for rid in rejected_ids:
                        self._mark_failed(conn, [rid], errors_by_id[rid])

                    logger.info(
                        "Da flush %d/%d ban ghi tu %s (Batch %s, latency %dms, Cloud tu choi %d)",
                        len(accepted_ids),
                        len(row_ids),
                        self.site_code,
                        batch_id,
                        latency_ms,
                        len(rejected_ids),
                    )
                    return {
                        "status": "success" if not rejected_ids else "partial",
                        "batch_id": batch_id,
                        "flushed": len(accepted_ids),
                        "rejected": len(rejected_ids),
                        "corrupt_records": len(corrupt_ids),
                        "latency_ms": latency_ms,
                        "cloud_response": data,
                    }

                err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error("Cloud tu choi batch %s: %s", batch_id, err_msg)
                self._mark_failed(conn, row_ids, err_msg)
                return {"status": "cloud_rejected", "flushed": 0, "error": err_msg}

            except requests.RequestException as exc:
                err_msg = f"Network exception: {exc}"
                logger.warning("Mat ket noi Cloud khi flush batch %s: %s", batch_id, err_msg)
                self._mark_failed(conn, row_ids, err_msg)
                return {"status": "network_error", "flushed": 0, "error": err_msg}

    def purge_synced(self, keep_last: int = 1000) -> int:
        """Don dep cac ban ghi da sync thanh cong de tiet kiem dia edge."""
        with self._connection() as conn:
            total_synced = conn.execute("SELECT COUNT(*) FROM outbox WHERE synced = 1").fetchone()[0]
            if total_synced > keep_last:
                to_delete = total_synced - keep_last
                cur = conn.execute(
                    """
                    DELETE FROM outbox WHERE id IN (
                        SELECT id FROM outbox WHERE synced = 1 ORDER BY id ASC LIMIT ?
                    )
                    """,
                    (to_delete,),
                )
                conn.commit()
                return cur.rowcount
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge Store-and-Forward Sync Agent")
    parser.add_argument("--site", default=os.getenv("SITE_CODE", "SITE-NHA-A"), help="Ma chi nhanh (phai duoc dang ky o Cloud)")
    parser.add_argument("--cloud-url", default=os.getenv("CLOUD_API_URL", "http://127.0.0.1:8000"), help="Cloud API URL")
    parser.add_argument("--api-key", default=os.getenv("CONNECTOR_API_KEY", "dev-connector-key"), help="API Key")
    parser.add_argument("--db", default="edge_outbox.db", help="Path toi SQLite DB outbox")
    parser.add_argument("--flush", action="store_true", help="Chay flush outbox mot lan")
    parser.add_argument("--watch", action="store_true", help="Chay vong lap tu dong flush (dung doc trong systemd/container)")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("SYNC_INTERVAL_SECONDS", "60")),
        help="So giay giua hai lan flush khi dung --watch (toi thieu 5)",
    )
    parser.add_argument("--stats", action="store_true", help="In thong ke outbox")
    args = parser.parse_args()

    agent = EdgeSyncAgent(site_code=args.site, cloud_url=args.cloud_url, api_key=args.api_key, db_path=args.db)

    if args.stats:
        stats = agent.get_stats()
        print(json.dumps(stats, indent=2))
        return

    if args.watch:
        # Day la vong lap ma docstring hua ("mang phuc hoi -> tu dong flush").
        # Mat mang khong lam mat du lieu: outbox van giu, retry_count tang len.
        interval = max(5, args.interval)
        logger.info("Che do watch: flush moi %d giay. Ctrl-C de dung.", interval)
        try:
            while True:
                result = agent.flush_batch()
                if result.get("status") != "empty":
                    print(json.dumps(result, indent=2))
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Dung agent. Hang doi van giu nguyen trong outbox.")
        return

    if args.flush:
        res = agent.flush_batch()
        print(json.dumps(res, indent=2))
        return

    print("Agent san sang. Dung --flush de day hang doi mot lan, --watch de chay nen, hoac --stats de xem trang thai.")


if __name__ == "__main__":
    main()
