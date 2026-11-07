"""WebSocket /ws/telemetry phai duoc xac thuc va cat theo vai tro nhu REST.

Trinh duyet khong gui duoc header Authorization qua WebSocket nen token nam o query string.
Do van la mot token JWT that: sai/het han/vai tro da doi/user bi khoa -> dong 1008.

Luu y ve ma loi: router goi `websocket.close(1008)` TRUOC `accept()`. Tren server that
(uvicorn + websockets) Starlette bien dieu do thanh HTTP 403 ngay luc bat tay, client
khong bao gio duoc upgrade; TestClient thi mo phong thanh WebSocketDisconnect(1008).
Hai duong deu la "tu choi" - dung sua thanh accept-roi-close chi de test thay 1008.
"""

from __future__ import annotations

import json
from datetime import timedelta

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.database import SessionLocal
from app.main import _ws_snapshot
from app.models import Role, User
from app.security import scopes_for
from app.timeutil import utcnow

WS = "/ws/telemetry"
POLICY_VIOLATION = 1008


def _connect(client: TestClient, token: str | None):
    url = WS if token is None else f"{WS}?token={token}"
    return client.websocket_connect(url)


def _user_id(username: str) -> int:
    session = SessionLocal()
    try:
        return session.scalars(select(User.id).where(User.username == username)).one()
    finally:
        session.close()


def test_khong_co_token_thi_dong_ngay(seeded_client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc:
        with _connect(seeded_client, None):
            pass
    assert exc.value.code == POLICY_VIOLATION


def test_token_rac_bi_tu_choi(seeded_client: TestClient):
    with pytest.raises(WebSocketDisconnect) as exc:
        with _connect(seeded_client, "khong-phai-jwt"):
            pass
    assert exc.value.code == POLICY_VIOLATION


def test_token_ky_bang_khoa_khac_bi_tu_choi(seeded_client: TestClient):
    """Chong gia mao: dung thuat toan, dung user, con han - nhung sai khoa ky."""
    forged = pyjwt.encode(
        {
            "sub": str(_user_id("bgd")),
            "username": "bgd",
            "role": Role.BGD.value,
            "iat": utcnow(),
            "exp": utcnow() + timedelta(hours=1),
        },
        "khoa-cua-ke-tan-cong-0123456789abcdef",
        algorithm="HS256",
    )
    with pytest.raises(WebSocketDisconnect) as exc:
        with _connect(seeded_client, forged):
            pass
    assert exc.value.code == POLICY_VIOLATION


def test_bgd_nhan_du_nhiet_canh_bao_va_nang_luong(seeded_client: TestClient, tokens: dict):
    with _connect(seeded_client, tokens[Role.BGD.value]) as socket:
        payload = socket.receive_json()

    assert set(payload) == {"thermal_summary", "alerts", "energy"}
    assert payload["thermal_summary"]["total_units"] > 0


def test_van_hanh_khong_nhan_du_lieu_tien(seeded_client: TestClient, tokens: dict):
    """Van hanh chi thay Nhiet. Tien dien khong duoc lo qua duong WebSocket."""
    with _connect(seeded_client, tokens[Role.VANHANH.value]) as socket:
        payload = socket.receive_json()

    assert set(payload) == {"thermal_summary", "alerts"}


def test_ke_toan_bi_dong_vi_khong_co_scope_nhiet(seeded_client: TestClient, tokens: dict):
    with pytest.raises(WebSocketDisconnect) as exc:
        with _connect(seeded_client, tokens[Role.KETOAN.value]):
            pass
    assert exc.value.code == POLICY_VIOLATION


def test_token_cua_user_da_bi_khoa_khong_vao_duoc(seeded_client: TestClient, seeded: Session, tokens: dict):
    user = seeded.scalars(select(User).where(User.username == "bgd")).one()
    user.is_active = False
    seeded.commit()

    with pytest.raises(WebSocketDisconnect) as exc:
        with _connect(seeded_client, tokens[Role.BGD.value]):
            pass
    assert exc.value.code == POLICY_VIOLATION


def test_doi_vai_tro_o_db_thi_token_cu_het_hieu_luc(seeded_client: TestClient, seeded: Session, tokens: dict):
    """Ke toan duoc nang len van hanh: token cu (role=KETOAN) phai chet, khong duoc tin payload."""
    user = seeded.scalars(select(User).where(User.username == "ketoan")).one()
    user.role = Role.VANHANH.value
    seeded.commit()

    with pytest.raises(WebSocketDisconnect) as exc:
        with _connect(seeded_client, tokens[Role.KETOAN.value]):
            pass
    assert exc.value.code == POLICY_VIOLATION


def test_payload_telemetry_tach_cop_va_hieu_suat(seeded_client: TestClient, tokens: dict):
    """Duong day realtime cung phai giu dung nghiep vu: lo hoi khong co COP."""
    with _connect(seeded_client, tokens[Role.BGD.value]) as socket:
        payload = socket.receive_json()

    rows = {r["equipment_code"]: r for r in payload["thermal_summary"]["telemetry"]}
    boilers = [r for r in rows.values() if r["is_combustion"]]
    refrigeration = [r for r in rows.values() if r["is_refrigeration"]]

    assert boilers and refrigeration
    assert all(r["cop"] is None for r in boilers)
    assert all(r["efficiency_pct"] is None for r in refrigeration)


def test_snapshot_serializable_bang_encoder_mac_dinh(seeded: Session):
    """send_json dung json.dumps thuong, khong co jsonable_encoder cua FastAPI.

    Mot datetime lot vao payload la lam sap ca socket: client ngat ket noi va khong
    nhan duoc bat ky ban tin nao, trong khi REST van xanh -> bug rat de lot.
    """
    snapshot = _ws_snapshot(set(scopes_for(Role.BGD.value)))
    json.dumps(snapshot)
