"""Kiem chung chat che cac tinh nang cua Tru cot 2:
  1. He thong phan quyen da tang L1-L10 Enterprise Matrix.
  2. Nhat ky kiem toan bat bien (Immutable Audit Trail) voi chuoi ky HMAC-SHA256.
  3. Phat hien bat ky hanh vi sua doi trai phep (tamper-evident detection).
  4. Tu dong ghi log khi dang nhap va thao tac canh bao.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AuditLog, Role, User
from app.security import hash_password, scopes_for
from app.services import audit as audit_service
from app.services.audit import (
    _MAX_CHAIN_RETRIES,
    AuditChainConflictError,
    GENESIS_HASH,
    SIGNED_FIELDS,
    record_audit,
    verify_audit_chain,
)
from app.timeutil import utcnow


def test_all_10_roles_exist_and_mapped():
    expected_roles = {
        "BGD", "VANHANH", "KETOAN",
        "L1_CHAIRMAN", "L2_CEO",
        "L3_TECHNICAL_DIRECTOR", "L4_OPERATIONS_MANAGER", "L5_MAINTENANCE_ENGINEER",
        "L6_HACCP_AUDITOR", "L7_WAREHOUSE_DISPATCHER",
        "L8_CFO", "L9_BILLING_SPECIALIST", "L10_SALES_EXECUTIVE",
    }
    actual_roles = {r.value for r in Role}
    assert expected_roles.issubset(actual_roles)

    for role_name in actual_roles:
        scopes = scopes_for(role_name)
        assert isinstance(scopes, list)
        assert len(scopes) > 0, f"Role {role_name} phai co it nhat mot scope"


def test_executive_scopes_include_audit():
    assert "audit" in scopes_for(Role.L1_CHAIRMAN.value)
    assert "audit" in scopes_for(Role.L2_CEO.value)
    assert "audit" in scopes_for(Role.BGD.value)
    assert "audit" in scopes_for(Role.L8_CFO.value)
    assert "audit" in scopes_for(Role.L3_TECHNICAL_DIRECTOR.value)

    # Nhan vien cap duoi khong duoc phep xem audit log
    assert "audit" not in scopes_for(Role.L4_OPERATIONS_MANAGER.value)
    assert "audit" not in scopes_for(Role.L5_MAINTENANCE_ENGINEER.value)
    assert "audit" not in scopes_for(Role.L7_WAREHOUSE_DISPATCHER.value)
    assert "audit" not in scopes_for(Role.L10_SALES_EXECUTIVE.value)


def test_audit_trail_cryptographic_chain(session: Session):
    user = User(username="auditor", role=Role.L1_CHAIRMAN.value, full_name="Auditor One", password_hash=hash_password("Pass123!"))
    session.add(user)
    session.flush()

    # Ghi 3 log lien tiep
    log1 = record_audit(session, user, action="ACTION_1", resource_type="config", details={"param": 100})
    log2 = record_audit(session, user, action="ACTION_2", resource_type="alert", resource_id="12", details={"note": "ok"})
    log3 = record_audit(session, user, action="ACTION_3", resource_type="billing", details={"amount": 5000000})
    session.commit()

    # Kiem tra tinh xau chuoi
    assert log2.previous_hash == log1.signature_hash
    assert log3.previous_hash == log2.signature_hash

    # Kiem tra toan ven
    check = verify_audit_chain(session)
    assert check["verified"] is True
    assert check["status"] == "ok"


def test_audit_trail_detects_tampering(session: Session):
    user = User(username="admin_audit", role=Role.L2_CEO.value, full_name="Admin Audit", password_hash=hash_password("Pass123!"))
    session.add(user)
    session.flush()

    log1 = record_audit(session, user, action="ORIGINAL_ACTION", resource_type="setpoint", details={"temp": -25.0})
    session.commit()

    # Gia mao sua doi du lieu truc tiep trong DB
    log1.action = "TAMPERED_ACTION"
    session.commit()

    # He thong phat hien ngay vi hash khong khop
    check = verify_audit_chain(session)
    assert check["verified"] is False
    assert check["status"] == "tampered"
    assert check["broken_at_id"] == log1.id


#: Gia tri gia mao cho tung cot. Moi gia tri phai KHAC gia tri goc ma test ghi vao,
#: khong thi assert "that su da doi" ben duoi se do va loi se bi che khuat.
_TAMPERED_VALUE = {
    "timestamp": lambda entry, ctx: entry.timestamp.replace(year=2001),
    "user_id": lambda entry, ctx: ctx["decoy_id"],
    "username": lambda entry, ctx: "ke_gia_mao",
    "user_role": lambda entry, ctx: Role.L1_CHAIRMAN.value,
    "action": lambda entry, ctx: "HANH_DONG_GIA_MAO",
    "resource_type": lambda entry, ctx: "gia_mao",
    "resource_id": lambda entry, ctx: "999999",
    "ip_address": lambda entry, ctx: "203.0.113.66",
    "details": lambda entry, ctx: {"da_sua": True},
}


@pytest.mark.parametrize("field", sorted(SIGNED_FIELDS))
def test_sua_bat_ky_cot_nao_da_ky_deu_bi_phat_hien(session: Session, field: str):
    """Moi cot nam trong chu ky deu phai bi phat hien khi bi sua ngoai luong.

    Ban cu chi ky timestamp/user_id/action/resource_type/details va bo sot username,
    user_role, resource_id, ip_address. He qua that: nguoi co quyen ghi DB doi duoc
    "AI da lam" (username/user_role) va "lam TU DAU" (ip_address) ma
    verify_audit_chain van bao nguyen ven - dung nhung cot ma nguoi doc nhat ky kiem
    toan can nhat. Test cu chi sua `action` nen khong bao gio nhin thay lo hong nay;
    test nay chay het moi cot trong SIGNED_FIELDS de them cot moi ma quen ky thi do.
    """
    assert field in _TAMPERED_VALUE, f"them cot vao SIGNED_FIELDS ma chua co gia tri gia mao: {field}"

    user = User(
        username="chain_target", role=Role.L6_HACCP_AUDITOR.value,
        full_name="Chain Target", password_hash=hash_password("Pass123!"),
    )
    decoy = User(
        username="chain_decoy", role=Role.L9_BILLING_SPECIALIST.value,
        full_name="Decoy", password_hash=hash_password("Pass123!"),
    )
    session.add_all([user, decoy])
    session.commit()

    entry = record_audit(
        session, user, action="ACTION_GOC", resource_type="setpoint",
        resource_id="12", details={"temp": -25.0}, ip_address="10.0.0.5",
    )
    session.commit()
    assert verify_audit_chain(session)["verified"] is True

    original = getattr(entry, field)
    tampered = _TAMPERED_VALUE[field](entry, {"decoy_id": decoy.id})
    assert tampered != original, f"gia tri gia mao trung gia tri goc, test khong kiem tra gi: {field}"

    setattr(entry, field, tampered)
    session.commit()
    session.expire_all()

    with SessionLocal() as fresh:
        check = verify_audit_chain(fresh)

    assert check["verified"] is False, f"sua {field} ma chuoi van nguyen ven: {check}"
    assert check["status"] == "tampered"
    assert check["broken_at_id"] == entry.id


def test_chu_ky_van_khop_sau_khi_doc_lai_tu_db(session: Session):
    """Chu ky tinh luc ghi phai khop chu ky tinh tu gia tri doc lai tu DB.

    Ca nhat ky kiem toan dung tren dieu kien nay, va no de vo hon nhin:
    `_canonical_payload` goi `.isoformat()` cho datetime, nen chi can `utcnow()`
    tra ve datetime co mui gio (hoac cot doi sang `DateTime(timezone=True)`, hoac
    driver cat microsecond) la gia tri doc lai khac gia tri da ky -> MOI ban ghi cu
    bao "tampered" du khong ai sua gi. Cac test khac verify tren cung mot session
    nen doc tu identity map, khong di qua DB, va vi the khong bat duoc loi nay.
    """
    now = utcnow()
    assert now.tzinfo is None, (
        "utcnow() phai tra ve datetime naive-UTC: chu ky duoc tinh bang .isoformat(), "
        "ma gia tri doc lai tu DB mat tzinfo, nen chu ky luc ghi se khong bao gio "
        "khop chu ky luc verify va toan bo nhat ky kiem toan thanh vo nghia."
    )

    user = User(
        username="roundtrip", role=Role.L8_CFO.value,
        full_name="Round Trip", password_hash=hash_password("Pass123!"),
    )
    session.add(user)
    session.commit()

    for index in range(5):
        record_audit(
            session, user, action=f"ROUNDTRIP_{index}", resource_type="billing",
            resource_id=str(index), details={"so_tien": 5_000_000 + index},
            ip_address="10.0.0.5",
        )
    session.commit()

    written = [row.timestamp for row in session.scalars(select(AuditLog).order_by(AuditLog.id))]
    session.close()

    with SessionLocal() as fresh:
        check = verify_audit_chain(fresh)
        reread = [row.timestamp for row in fresh.scalars(select(AuditLog).order_by(AuditLog.id))]

    assert reread == written, (
        "timestamp bi bien doi khi di qua DB (mat microsecond hoac doi mui gio) "
        "- nguyen nhan lam chu ky lech ma khong phai do bi tan cong"
    )
    assert check["verified"] is True, check
    assert check["total_records"] == 5


def _audit_user(session: Session, username: str, role: Role = Role.L4_OPERATIONS_MANAGER) -> User:
    user = User(
        username=username, role=role.value,
        full_name=username.title(), password_hash=hash_password("Pass123!"),
    )
    session.add(user)
    session.commit()
    return user


def test_tranh_chap_dau_chuoi_khong_tao_fork(session: Session, monkeypatch: pytest.MonkeyPatch):
    """Hai ben cung doc mot dau chuoi thi van chi duoc phep ton tai mot nhanh chuoi.

    `record_audit` khoa dau chuoi bang FOR UPDATE, nhung SQLAlchemy AM THAM bo qua
    FOR UPDATE tren SQLite - nghia la dev va test chay khong co khoa nao ca, chi prod
    (Postgres) moi that su khoa. Vi the chot chan dung la UNIQUE(previous_hash) khai
    bao trong models.py: no bien fork thanh IntegrityError ro rang de `record_audit`
    doc lai dau chuoi va ghi tiep.

    Thieu rang buoc do thi fork nhin giong het bi tan cong: verify_audit_chain bao
    "tampered" vinh vien ma khong ai phan biet duoc la loi dong bo hay co nguoi sua
    nhat ky - va mot nhat ky kiem toan khong phan biet duoc hai truong hop do thi
    khong dung lam bang chung duoc.
    """
    user = _audit_user(session, "racer")
    record_audit(session, user, action="FIRST", resource_type="test")
    session.commit()
    stale_head = session.scalars(
        select(AuditLog.signature_hash).order_by(desc(AuditLog.id)).limit(1)
    ).one()

    # Mot tien trinh khac chen vao va commit truoc khi ben nay kip ghi.
    record_audit(session, user, action="OTHER_PROCESS_COMMITTED_FIRST", resource_type="test")
    session.commit()

    real_head = audit_service._chain_head_hash
    calls = {"count": 0}

    def stale_on_first_call(active_session: Session) -> str:
        calls["count"] += 1
        return stale_head if calls["count"] == 1 else real_head(active_session)

    monkeypatch.setattr(audit_service, "_chain_head_hash", stale_on_first_call)
    record_audit(session, user, action="RACED", resource_type="test")
    session.commit()

    assert calls["count"] > 1, (
        "record_audit khong doc lai dau chuoi sau khi va UNIQUE - tuc la no khong "
        "tu phuc hoi duoc tranh chap va ban ghi se bi mat hoac tao fork"
    )

    forked = session.execute(
        select(AuditLog.previous_hash, func.count(AuditLog.id))
        .group_by(AuditLog.previous_hash)
        .having(func.count(AuditLog.id) > 1)
    ).all()
    assert not forked, f"chuoi bi fork, co previous_hash dung cho nhieu ban ghi: {forked}"
    assert session.scalar(select(func.count(AuditLog.id))) == 3, "mat ban ghi khi xu ly tranh chap"
    assert verify_audit_chain(session)["verified"] is True


def test_khong_noi_duoc_chuoi_thi_tu_choi_hanh_dong(
    session: Session, monkeypatch: pytest.MonkeyPatch
):
    """Fail-closed: khong ghi duoc nhat ky thi hanh dong bi tu choi, khong lot qua.

    Mot thao tac khong co dau vet trong nhat ky kiem toan te hon nhieu mot thao tac
    bi tu choi: nguoi van hanh tin rang da ghi log, va den luc kiem toan moi phat
    hien thieu bang chung - luc do khong con cach nao lay lai. Vi the `record_audit`
    nem AuditChainConflictError (FastAPI bien thanh HTTP 500) thay vi nuot loi roi
    tra ve nhu the da ghi thanh cong.
    """
    user = _audit_user(session, "blocked")
    record_audit(session, user, action="DA_GHI_TRUOC_DO", resource_type="test")
    session.commit()
    before = session.scalar(select(func.count(AuditLog.id)))

    # Dau chuoi bi keo ve GENESIS vinh vien: moi lan insert deu va UNIQUE cua ban
    # ghi dau tien. Day la tinh huong chuoi da fork that su hoac DB dang bi khoa.
    attempts = {"count": 0}

    def broken_head(active_session: Session) -> str:
        attempts["count"] += 1
        return GENESIS_HASH

    monkeypatch.setattr(audit_service, "_chain_head_hash", broken_head)

    with pytest.raises(AuditChainConflictError) as excinfo:
        record_audit(session, user, action="PHAI_BI_TU_CHOI", resource_type="test")
    session.rollback()

    assert attempts["count"] == _MAX_CHAIN_RETRIES, (
        f"phai thu dung {_MAX_CHAIN_RETRIES} lan truoc khi tu bo, thuc te doc dau chuoi "
        f"{attempts['count']} lan"
    )
    assert "tu choi" in str(excinfo.value), (
        "thong bao phai noi ro la hanh dong bi tu choi, de nguoi van hanh khong tuong "
        f"la da ghi log thanh cong: {excinfo.value}"
    )
    assert isinstance(excinfo.value.__cause__, Exception), (
        "phai giu nguyen IntegrityError goc lam __cause__ de truy nguyen la fork hay DB khoa"
    )

    assert session.scalar(select(func.count(AuditLog.id))) == before, (
        "ban ghi khong noi duoc chuoi van lot vao bang - nhat ky luc nay khong con tin duoc"
    )
    assert verify_audit_chain(session)["verified"] is True


def test_api_audit_endpoints(seeded_client: TestClient, seeded: Session):
    # Lay user bgd da seed de login
    login_res = seeded_client.post("/api/auth/login", json={"username": "bgd", "password": "TestPass!2026"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Goi API verify audit chain
    verify_res = seeded_client.get("/api/audit/verify", headers=headers)
    assert verify_res.status_code == 200
    assert verify_res.json()["verified"] is True

    # Goi API list audit logs
    list_res = seeded_client.get("/api/audit/logs", headers=headers)
    assert list_res.status_code == 200
    data = list_res.json()
    assert "items" in data
    # Phai co it nhat log dang nhap cua bgd
    actions = [item["action"] for item in data["items"]]
    assert "USER_LOGIN" in actions
