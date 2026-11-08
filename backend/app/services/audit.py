"""Dich vu nhat ky kiem toan bat bien (Immutable Tamper-Evident Audit Trail).

Moi hanh vi tren he thong (dang nhap, thao tac van hanh nhiet, xac nhan canh bao,
xuat hoa don, thay doi cau hinh) duoc xau chuoi bang chu ky HMAC-SHA256 lien ket voi
ban ghi lien truoc (tuong tu Blockchain). Bat ky hanh vi sua doi truc tiep trong
Database deu bi phat hien ngay tuc thi qua ham verify_audit_chain().

Ba diem thiet ke can doc truoc khi sua file nay:

1. HMAC CO KHOA, khong phai SHA-256 thuan. SHA-256 thuan thi ai cung tinh lai duoc,
   nen nguoi co quyen ghi DB (DBA, hoac attacker lay duoc dump) sua ban ghi roi bam
   lai hash cho khop - chuoi van "verified" va he thong bao cao sai rang khong ai can
   thiep. Khoa dan xuat tu JWT_SECRET_KEY theo domain separation, cung cach lam voi
   chung chi HACCP trong services/compliance.py.

2. KY HET MOI COT CO THE SUA. Ban cu chi ky (prev, timestamp, user_id, action,
   resource_type, details) va bo qua resource_id, ip_address, username, user_role:
   doi "xac nhan canh bao so 12" thanh "so 9999", hoac xoa IP nguon, ma chuoi van
   bao nguyen ven. Danh sach cot duoc ky nam o SIGNED_FIELDS.

3. MOT BAN GHI CHI CO MOT BAN KE NHIEM. `previous_hash` mang UNIQUE index nen hai
   tien trinh ghi dong thoi khong the cung tao hai nhanh chuoi (fork) - mot trong hai
   se nhan IntegrityError va duoc ghi lai tu dau chuoi moi. Khong co rang buoc nay thi
   fork nhin giong het tampering: nhat ky kiem toan tu huy vinh vien ma khong ai biet
   la do loi dong bo hay do bi tan cong.

Luu y khi doi khoa hoac doi SIGNED_FIELDS: moi chu ky da luu truoc do se khong khop
nua va verify_audit_chain() bao "tampered". Do la hanh vi dung (chu ky cu khong con
gia tri voi khoa moi), khong phai loi - nhung phai noi cho nguoi van hanh biet truoc.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AUDIT_GENESIS_HASH, AuditLog, User
from ..timeutil import utcnow

logger = logging.getLogger("audit-trail")

#: Ban ghi dau tien cua chuoi truyen lai gia tri nay. Lay tu models de cot
#: `audit_logs.previous_hash` (co default) va dich vu nay khong the lech nhau.
GENESIS_HASH = AUDIT_GENESIS_HASH

#: Nguyen lieu dan xuat khoa ky chuoi audit, tach biet voi khoa JWT va khoa chung chi
#: HACCP de lo mot khoa thi hai khoa kia khong bi dung lai duoc (domain separation).
_CHAIN_KEY_INFO = b"thermalbiz-audit-chain-v1"

#: Cac cot duoc dua vao chu ky. Them cot moi vao AuditLog thi phai them vao day, neu
#: khong cot do sua duoc ma verify van bao "nguyen ven".
SIGNED_FIELDS: Tuple[str, ...] = (
    "timestamp",
    "user_id",
    "username",
    "user_role",
    "action",
    "resource_type",
    "resource_id",
    "ip_address",
    "details",
)

#: So lan thu ghi lai khi hai tien trinh tranh nhau dau chuoi. Voi FOR UPDATE tren
#: Postgres thi gan nhu khong bao gio dung den; con lai la truong hop chuoi dang rong
#: (khong co ban ghi nao de khoa) va hai tien trinh cung lay GENESIS lam moc.
_MAX_CHAIN_RETRIES = 3

#: So ban ghi doc len moi dot khi verify, tranh nap ca bang vao RAM.
_VERIFY_BATCH_SIZE = 500


class AuditChainConflictError(RuntimeError):
    """Khong noi duoc ban ghi vao chuoi sau nhieu lan thu.

    Nghiep vu phai that bai (fail-closed): mot hanh dong khong ghi duoc vao nhat ky
    kiem toan thi khong duoc phep dien ra am tham, vi ca muc dich cua nhat ky la
    khong de hanh dong nao khong co dau vet.
    """


def _signing_key() -> bytes:
    secret = get_settings().jwt_secret_key
    if not secret:
        # Ky bang khoa rong thi chu ky ai cung gia mao duoc. Bao loi con hon la tao ra
        # mot nhat ky kiem toan trong co ve an toan nhung khong co gia tri phap ly.
        raise RuntimeError("JWT_SECRET_KEY rong - khong the ky chuoi audit log.")
    return hmac.new(secret.encode("utf-8"), _CHAIN_KEY_INFO, hashlib.sha256).digest()


def _canonical_payload(values: Mapping[str, Any]) -> str:
    """Chuan hoa cac cot duoc ky thanh mot chuoi on dinh giua luc ky va luc kiem tra.

    `details` duoc dump rieng voi sort_keys vi thu key trong JSON khong duoc phep doi
    chu ky; `timestamp` lay isoformat() - dung dang ma ca SQLite lan Postgres luu va
    doc lai nguyen ven den microsecond, nen chu ky tinh luc ghi van khop luc verify.
    """
    normalized: Dict[str, Any] = {}
    for field in SIGNED_FIELDS:
        value = values[field]
        if field == "details":
            normalized[field] = json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        elif isinstance(value, datetime):
            normalized[field] = value.isoformat()
        else:
            normalized[field] = value
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_audit_hash(previous_hash: str, values: Mapping[str, Any]) -> str:
    """Chu ky HMAC-SHA256 cua mot ban ghi, xau chuoi voi chu ky cua ban ghi truoc do."""
    message = f"{previous_hash}|{_canonical_payload(values)}"
    return hmac.new(_signing_key(), message.encode("utf-8"), hashlib.sha256).hexdigest()


def _signed_values(entry: AuditLog) -> Dict[str, Any]:
    return {field: getattr(entry, field) for field in SIGNED_FIELDS}


def _chain_head_hash(session: Session) -> str:
    """Chu ky cua ban ghi cuoi chuoi, hoac GENESIS neu chuoi con rong.

    `with_for_update()`: Postgres khoa ban ghi dau chuoi de hai tien trinh khong cung
    doc mot gia tri roi cung bam vao do. SQLite khong ho tro FOR UPDATE va SQLAlchemy
    am tham bo qua (da kiem chung: cau SELECT sinh ra khong co FOR UPDATE) - tren do
    UNIQUE index cua previous_hash la vong chan thuc su.
    """
    head = session.scalars(
        select(AuditLog.signature_hash).order_by(desc(AuditLog.id)).limit(1).with_for_update()
    ).first()
    return GENESIS_HASH if head is None else head


def record_audit(
    session: Session,
    user: Optional[User],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> AuditLog:
    """Ghi mot ban ghi audit log moi vao chuoi bat bien.

    Chay trong transaction dang mo cua ben goi va KHONG tu commit: neu nghiep vu chinh
    rollback thi ban ghi audit cung rollback theo, khong de lai nhat ky cua mot hanh
    dong chua tung xay ra.
    """
    now = utcnow()
    username = user.username if user else "SYSTEM"
    user_role = str(user.role) if user else "SYSTEM"
    user_id = user.id if user else None
    clean_details = details or {}

    last_error: Optional[IntegrityError] = None
    for attempt in range(_MAX_CHAIN_RETRIES):
        previous_hash = _chain_head_hash(session)
        # Tao object moi moi lan thu: lan truoc do da bi savepoint rollback day ra khoi
        # session, tai dung no thi trang thai khong con dang tin.
        entry = AuditLog(
            timestamp=now,
            user_id=user_id,
            username=username,
            user_role=user_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            details=clean_details,
        )
        # Ky tren chinh cac cot vua dat (SIGNED_FIELDS), khong viet lai danh sach cot
        # o day: hai danh sach lech nhau thi co cot nam ngoai chu ky ma khong ai biet.
        entry.previous_hash = previous_hash
        entry.signature_hash = compute_audit_hash(previous_hash, _signed_values(entry))
        try:
            # SAVEPOINT: IntegrityError o day chi huy dung lan chen nay, khong huy ca
            # transaction cua ben goi (vi du luc xac nhan canh bao thi gia tri
            # alert.acknowledged_at vua dat phai con nguyen de ghi tiep lan sau).
            with session.begin_nested():
                session.add(entry)
                session.flush()
        except IntegrityError as exc:
            last_error = exc
            logger.warning(
                "Hai tien trinh tranh nhau dau chuoi audit (lan %d/%d), doc lai dau chuoi va ghi tiep.",
                attempt + 1,
                _MAX_CHAIN_RETRIES,
            )
            continue

        logger.info(
            "Audit recorded: [%s] by %s (%s) on %s/%s",
            action,
            username,
            user_role,
            resource_type,
            resource_id,
        )
        return entry

    raise AuditChainConflictError(
        f"Khong noi duoc ban ghi audit vao chuoi sau {_MAX_CHAIN_RETRIES} lan thu. "
        "Co the chuoi dang bi fork hoac DB dang khoa - hanh dong nay bi tu choi de "
        "khong de lai mot thao tac khong co dau vet trong nhat ky kiem toan."
    ) from last_error


def verify_audit_chain(session: Session) -> Dict[str, Any]:
    """Kiem tra toan ven chuoi audit log, phat hien ngay neu co sua doi trai phep.

    Doc tuan tu theo tung dot (`yield_per`) thay vi nap ca bang vao RAM: day la bang
    lon nhat he thong va chi lon dan theo thoi gian, mot lan kiem tra khong duoc phep
    tieu thu bo nho ty le thuan voi so nam van hanh.
    """
    expected_prev = GENESIS_HASH
    total = 0
    failure: Optional[Dict[str, Any]] = None

    result = session.scalars(
        select(AuditLog)
        .order_by(AuditLog.id.asc())
        .execution_options(yield_per=_VERIFY_BATCH_SIZE)
    )
    try:
        for log in result:
            total += 1
            if log.previous_hash != expected_prev:
                failure = {
                    "status": "tampered",
                    "verified": False,
                    "broken_at_id": log.id,
                    "checked_records": total,
                    "total_records": total,
                    "expected_previous_hash": expected_prev,
                    "found_previous_hash": log.previous_hash,
                    "error": f"Ban ghi #{log.id} khong noi dung vao chuoi: previous_hash lech gia tri da ky.",
                }
                break

            expected_sig = compute_audit_hash(log.previous_hash, _signed_values(log))
            if not hmac.compare_digest(log.signature_hash or "", expected_sig):
                failure = {
                    "status": "tampered",
                    "verified": False,
                    "broken_at_id": log.id,
                    "checked_records": total,
                    "total_records": total,
                    "error": f"Chu ky cua ban ghi #{log.id} khong khop noi dung dang luu.",
                }
                break

            expected_prev = log.signature_hash
    finally:
        # Dong stream truoc khi tra ket qua: neu break giua chung thi cursor van con mo
        # tren cung mot connection ma lenh SELECT tiep theo se dung lai.
        result.close()

    if failure is not None:
        return failure

    if total == 0:
        return {
            "status": "ok",
            "verified": True,
            "total_records": 0,
            "checked_records": 0,
            "latest_signature": None,
            "message": "Chuoi audit log dang rong, chua co ban ghi nao de kiem tra.",
        }

    return {
        "status": "ok",
        "verified": True,
        "total_records": total,
        "checked_records": total,
        "latest_signature": expected_prev,
        "message": f"Toan bo {total} ban ghi audit log nguyen ven, chu ky khop day du.",
    }
