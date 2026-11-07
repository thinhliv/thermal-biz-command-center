"""JWT + RBAC 3 vai: BGD thay het, Van hanh chi Nhiet+Canh bao, Ke toan chi Kinh doanh+Cong no.

Diem trong tam: du lieu phai bi CAT O SERVER. Tra ve het roi bao frontend an di
van lo du lieu qua network.
"""

from __future__ import annotations

import jwt as pyjwt
from fastapi.testclient import TestClient

from app.config import get_settings
from app.security import ROLE_SCOPES

PASSWORD = "TestPass!2026"

THERMAL_ONLY = ["/api/thermal", "/api/thermal/summary", "/api/thermal/rules", "/api/alerts", "/api/alerts/stats"]
FINANCE_ONLY = ["/api/business", "/api/business/orders", "/api/business/tariff", "/api/debts", "/api/debts/customers"]


def _login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# --------------------------------------------------------------------------- #
# Dang nhap
# --------------------------------------------------------------------------- #
def test_login_returns_token_and_scopes(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    response = _login(seeded_client, "bgd")
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in_minutes"] == get_settings().jwt_expire_minutes
    assert body["user"]["scopes"] == ROLE_SCOPES["BGD"]
    # Mat khau khong bao gio duoc tra ve
    assert "password" not in body["user"] and "password_hash" not in body["user"]


def test_login_wrong_password_is_401(seeded_client: TestClient) -> None:
    assert _login(seeded_client, "bgd", "sai-mat-khau").status_code == 401


def test_login_unknown_user_is_401_not_404(seeded_client: TestClient) -> None:
    """Khong duoc lo ra tai khoan nao ton tai."""
    assert _login(seeded_client, "khong-ton-tai", PASSWORD).status_code == 401


def test_login_rejects_inactive_account(seeded_client: TestClient, seeded) -> None:
    from app.models import User
    from sqlalchemy import select

    user = seeded.scalars(select(User).where(User.username == "ketoan")).one()
    user.is_active = False
    seeded.commit()
    assert _login(seeded_client, "ketoan").status_code == 403


def test_me_returns_current_user(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    body = seeded_client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['VANHANH']}"}).json()
    assert body["username"] == "vanhanh"
    assert body["role"] == "VANHANH"


def test_missing_token_is_rejected(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/thermal").status_code in (401, 403)


def test_garbage_token_is_rejected(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/thermal", headers={"Authorization": "Bearer khong.phai.jwt"}).status_code == 401


def test_token_signed_with_other_secret_is_rejected(seeded_client: TestClient, seeded) -> None:
    """Chung minh JWT duoc ky bang JWT_SECRET_KEY, khong phai 'none'/khoa tu chon."""
    from app.models import User
    from sqlalchemy import select

    user = seeded.scalars(select(User).where(User.username == "ketoan")).one()
    forged = pyjwt.encode(
        {"sub": str(user.id), "role": "BGD", "username": user.username, "exp": 9_999_999_999},
        "khoa-cua-ke-tan-cong-0123456789abcdef",
        algorithm="HS256",
    )
    assert seeded_client.get("/api/thermal", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_role_downgrade_in_token_is_rejected(seeded_client: TestClient, seeded) -> None:
    """Token ghi BGD nhung DB luu KETOAN -> tu choi (DB la nguon that)."""
    from app.models import User
    from app.security import create_access_token
    from sqlalchemy import select

    user = seeded.scalars(select(User).where(User.username == "ketoan")).one()
    token, _ = create_access_token(user)
    payload = pyjwt.decode(token, get_settings().jwt_secret_key, algorithms=["HS256"])
    payload["role"] = "BGD"
    tampered = pyjwt.encode(payload, get_settings().jwt_secret_key, algorithm="HS256")
    assert seeded_client.get("/api/thermal", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


# --------------------------------------------------------------------------- #
# Phan quyen theo endpoint
# --------------------------------------------------------------------------- #
def test_vanhanh_chi_vao_duoc_nhiet_va_canh_bao(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    headers = {"Authorization": f"Bearer {tokens['VANHANH']}"}
    for path in THERMAL_ONLY:
        assert seeded_client.get(path, headers=headers).status_code == 200, path
    for path in FINANCE_ONLY:
        assert seeded_client.get(path, headers=headers).status_code == 403, path


def test_ketoan_chi_vao_duoc_kinh_doanh_va_cong_no(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    headers = {"Authorization": f"Bearer {tokens['KETOAN']}"}
    for path in FINANCE_ONLY:
        assert seeded_client.get(path, headers=headers).status_code == 200, path
    for path in THERMAL_ONLY:
        assert seeded_client.get(path, headers=headers).status_code == 403, path


def test_bgd_thay_tat_ca(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    headers = {"Authorization": f"Bearer {tokens['BGD']}"}
    for path in THERMAL_ONLY + FINANCE_ONLY:
        assert seeded_client.get(path, headers=headers).status_code == 200, path


def test_chi_bgd_duoc_tao_nguong_canh_bao(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    rule = {
        "applies_to_kind": "COLD_ROOM",
        "metric": "temperature_c",
        "comparator": "GT",
        "threshold": 6.0,
        "duration_minutes": 10,
        "severity": "WARNING",
        "message_template": "{equipment}: {value:.1f}C vuot {threshold:.1f}C",
    }
    assert seeded_client.post("/api/thermal/rules", json=rule, headers={"Authorization": f"Bearer {tokens['BGD']}"}).status_code == 201
    for role in ("VANHANH", "KETOAN"):
        response = seeded_client.post(
            "/api/thermal/rules", json=rule, headers={"Authorization": f"Bearer {tokens[role]}"}
        )
        assert response.status_code == 403, role


# --------------------------------------------------------------------------- #
# Cat du lieu dashboard theo vai
# --------------------------------------------------------------------------- #
def _summary(client: TestClient, token: str) -> dict:
    response = client.get("/api/dashboard-summary", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    return response.json()


def test_dashboard_vanhanh_khong_thay_tien(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    body = _summary(seeded_client, tokens["VANHANH"])
    assert set(body) - {"_meta"} == {"thermal_summary", "alerts"}
    assert body["_meta"]["role"] == "VANHANH"


def test_dashboard_ketoan_khong_thay_nhiet(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    body = _summary(seeded_client, tokens["KETOAN"])
    assert set(body) - {"_meta"} == {"business", "debts", "energy", "load_shift"}
    assert "thermal_summary" not in body and "alerts" not in body


def test_dashboard_bgd_thay_het(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    body = _summary(seeded_client, tokens["BGD"])
    assert set(body) - {"_meta"} == {"thermal_summary", "alerts", "business", "debts", "energy", "load_shift"}


def test_stream_snapshot_chi_co_nhiet_va_canh_bao(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    body = seeded_client.get(
        "/api/dashboard-summary/stream-snapshot", headers={"Authorization": f"Bearer {tokens['BGD']}"}
    ).json()
    assert set(body) <= {"thermal_summary", "alerts"}
    # Ke toan khong co scope thermal/alerts -> snapshot rong
    assert seeded_client.get(
        "/api/dashboard-summary/stream-snapshot", headers={"Authorization": f"Bearer {tokens['KETOAN']}"}
    ).json() == {}


# --------------------------------------------------------------------------- #
# Endpoint cong khai
# --------------------------------------------------------------------------- #
def test_health_khong_can_token(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_system_config_khong_lo_secret(client: TestClient) -> None:
    body = client.get("/api/system/config").json()
    dumped = str(body).lower()
    for secret in ("jwt_secret", "connector_api_key", "password", get_settings().jwt_secret_key.lower()):
        assert secret not in dumped


def test_cors_khong_dung_wildcard_voi_credentials() -> None:
    from app.main import app as main_app

    for middleware in main_app.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            assert middleware.kwargs["allow_origins"] != ["*"]
            assert get_settings().cors_origins != ["*"]
