"""Kiem chung chat che cac tinh nang cua Tru cot 2:
  1. He thong phan quyen da tang L1-L10 Enterprise Matrix.
  2. Nhat ky kiem toan bat bien (Immutable Audit Trail) voi cryptographic SHA-256 chain.
  3. Phat hien bat ky hanh vi sua doi trai phep (tamper-evident detection).
  4. Tu dong ghi log khi dang nhap va thao tac canh bao.
"""

from __future__ import annotations

import json
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Role, User
from app.security import (
    AuditRoles,
    ExecutiveOnly,
    FinanceRoles,
    ROLE_SCOPES,
    ThermalRoles,
    create_access_token,
    hash_password,
    scopes_for,
)
from app.services.audit import compute_audit_hash, record_audit, verify_audit_chain


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
