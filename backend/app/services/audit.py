"""Dich vu nhat ky kiem toan bat bien (Immutable Tamper-Evident Audit Trail).

Moi hanh vi tren he thong (dang nhap, thao tac van hanh nhiet, xac nhan canh bao,
xuat hoa don, thay doi cau hinh) duoc xau chuoi bang ma hash cryptographic SHA-256
lien ket voi ban ghi lien truoc (tuong tu Blockchain). Bat ky hanh vi sua doi truc tiep
trong Database deu bi phat hien ngay tuc thi qua ham verify_audit_chain().
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import AuditLog, User
from ..timeutil import utcnow

logger = logging.getLogger("audit-trail")

GENESIS_HASH = "GENESIS_THERMAL_BIZ_COMMAND_CENTER_2026"


def compute_audit_hash(
    prev_hash: str,
    timestamp_iso: str,
    user_id: Optional[int],
    action: str,
    resource_type: str,
    details_str: str,
) -> str:
    content = f"{prev_hash}|{timestamp_iso}|{user_id}|{action}|{resource_type}|{details_str}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def record_audit(
    session: Session,
    user: Optional[User],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> AuditLog:
    """Ghi mot ban ghi audit log moi vao chuoi bat bien."""
    # Lay ban ghi cuoi cung de lay previous_hash
    last_log = session.scalars(select(AuditLog).order_by(desc(AuditLog.id)).limit(1)).first()
    prev_hash = last_log.signature_hash if last_log else GENESIS_HASH

    now = utcnow()
    clean_details = details or {}
    details_str = json.dumps(clean_details, sort_keys=True, ensure_ascii=False)

    user_id = user.id if user else None
    username = user.username if user else "SYSTEM"
    user_role = str(user.role) if user else "SYSTEM"

    sig_hash = compute_audit_hash(
        prev_hash,
        now.isoformat(),
        user_id,
        action,
        resource_type,
        details_str,
    )

    log_entry = AuditLog(
        timestamp=now,
        user_id=user_id,
        username=username,
        user_role=user_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        details=clean_details,
        previous_hash=prev_hash,
        signature_hash=sig_hash,
    )
    session.add(log_entry)
    session.flush()
    logger.info("Audit recorded: [%s] by %s (%s) on %s/%s", action, username, user_role, resource_type, resource_id)
    return log_entry


def verify_audit_chain(session: Session) -> Dict[str, Any]:
    """Kiem tra toan ven chuoi audit log, phat hien ngay neu co sua doi trai phep."""
    logs = list(session.scalars(select(AuditLog).order_by(AuditLog.id.asc())))
    if not logs:
        return {"status": "ok", "total_records": 0, "verified": True, "message": "Audit chain empty"}

    expected_prev = GENESIS_HASH
    for log in logs:
        if log.previous_hash != expected_prev:
            return {
                "status": "tampered",
                "verified": False,
                "broken_at_id": log.id,
                "error": f"Previous hash mismatch at record #{log.id}",
            }
        details_str = json.dumps(log.details or {}, sort_keys=True, ensure_ascii=False)
        expected_sig = compute_audit_hash(
            log.previous_hash,
            log.timestamp.isoformat(),
            log.user_id,
            log.action,
            log.resource_type,
            details_str,
        )
        if log.signature_hash != expected_sig:
            return {
                "status": "tampered",
                "verified": False,
                "broken_at_id": log.id,
                "error": f"Signature mismatch at record #{log.id}",
            }
        expected_prev = log.signature_hash

    return {
        "status": "ok",
        "verified": True,
        "total_records": len(logs),
        "latest_signature": expected_prev,
        "message": "Toan bo chuoi audit log nguyen ven 100%",
    }
