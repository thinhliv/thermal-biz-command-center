"""JWT + RBAC 13 vai: 3 vai co ban (BGD/VANHANH/KETOAN) + ma tran L1-L10 Enterprise.

Diem trong tam: du lieu phai bi CAT O SERVER. Tra ve het roi bao frontend an di
van lo du lieu qua network.

Diem trong tam thu hai: `scopes_for()` va cac bundle `require_roles(...)` phai khop nhau.
Frontend ve tab dua tren scopes trong `/api/auth/me`, nen cap scope ma endpoint van 403
la tab mo ra chi de hien loi - L6_HACCP_AUDITOR tung bi dung nhu vay voi bao cao HACCP.
"""

from __future__ import annotations

import re
from pathlib import Path

import jwt as pyjwt
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import Role
from app.seed import DEMO_USERS
from app.security import ALL_SCOPES, ROLE_SCOPES, scopes_for

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
# Ma tran L1-L10: scopes phai khop voi bundle quyen that
# --------------------------------------------------------------------------- #
#: Endpoint doc nhe nhat cua tung scope. `overview` khong co o day vi no bi cat theo NOI
#: DUNG ben trong /api/dashboard-summary (moi vai deu goi duoc, chi khac phan tra ve)
#: chu khong chan o endpoint.
SCOPE_PROBES = {
    "thermal": "/api/thermal/summary",
    "alerts": "/api/alerts",
    "business": "/api/business",
    "debts": "/api/debts",
    "audit": "/api/audit/logs",
    "compliance": "/api/compliance/haccp/audit",
    "ai": "/api/ai/peak-shaving/schedule",
    "sync": "/api/sync/status",
}


def test_moi_vai_dang_nhap_duoc_va_nhan_dung_scopes(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    """13 vai deu phai dang nhap that qua HTTP duoc, khong chi ton tai trong enum.

    `User.role` tung la `String(16)` trong khi 6/13 ten dai 23 ky tu. SQLite khong rang
    buoc do dai nen seed van "chay", Postgres thi cat/tu choi - loi chi lo khi len prod.
    """
    for username, role, _, _ in DEMO_USERS:
        body = _login(seeded_client, username).json()
        assert body["access_token"], username

        me = seeded_client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens[role.value]}"}).json()
        assert me["role"] == role.value, username
        assert me["scopes"] == scopes_for(role.value), username
        assert me["scopes"], f"Vai {role.value} khong co scope nao -> frontend khong co trang dich de ve"


def test_scope_da_cap_thi_endpoint_do_khong_duoc_403(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    """Chieu nguy hiem: `/api/auth/me` bao co scope ma goi API cua scope do thi 403.

    Truoc day L6_HACCP_AUDITOR co `compliance` trong ROLE_SCOPES nhung bundle
    `ComplianceRoles` khong liet ke L6 - vai chuyen kiem toan HACCP bi khoa khoi chinh
    bao cao HACCP. Test nay bat loi do cho ca 13 vai x 8 scope ma khong phai liet ke tay.
    """
    for username, role, _, _ in DEMO_USERS:
        headers = {"Authorization": f"Bearer {tokens[role.value]}"}
        for scope in scopes_for(role.value):
            path = SCOPE_PROBES.get(scope)
            if path is None:
                continue
            status = seeded_client.get(path, headers=headers).status_code
            assert status != 403, f"{role.value} co scope {scope} nhung {path} tra 403"
            # Path ma sai thi assert 403 o tren van pass am tham (404 != 403).
            assert status != 404, f"SCOPE_PROBES tro vao {path} khong ton tai - router that da doi"


def test_l6_phat_hanh_duoc_chung_chi_haccp(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    """Nghiep vu gan voi vai tro: L6 la nguoi lap va ky chung nhan kiem toan chuoi lanh."""
    payload = {"batch_name": "Lô cá tra phi lê đông lạnh", "hours": 24}
    headers = {"Authorization": f"Bearer {tokens['L6_HACCP_AUDITOR']}"}
    response = seeded_client.post("/api/compliance/haccp/certificate", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ISSUED"


def test_vai_khong_phan_su_bi_chan_khoi_bao_cao_haccp_esg(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    """So lan vi pham nguong nhiet do khong phai thong tin cua khoi billing/kinh doanh.

    Dung `AnyRole` cho hai endpoint nay thi ai dang nhap cung doc duoc bao cao kiem toan.
    """
    for role in ("L9_BILLING_SPECIALIST", "L10_SALES_EXECUTIVE", "L7_WAREHOUSE_DISPATCHER"):
        headers = {"Authorization": f"Bearer {tokens[role]}"}
        for path in ("/api/compliance/haccp/audit", "/api/compliance/esg/carbon-footprint?refrigerant_leak_kg=0"):
            assert seeded_client.get(path, headers=headers).status_code == 403, f"{role} doc duoc {path}"


def test_vai_khong_phan_su_bi_chan_khoi_nhat_ky_kiem_toan(seeded_client: TestClient, tokens: dict[str, str]) -> None:
    for role in ("VANHANH", "L5_MAINTENANCE_ENGINEER", "L7_WAREHOUSE_DISPATCHER", "L10_SALES_EXECUTIVE"):
        headers = {"Authorization": f"Bearer {tokens[role]}"}
        for path in ("/api/audit/logs", "/api/audit/verify"):
            assert seeded_client.get(path, headers=headers).status_code == 403, f"{role} doc duoc {path}"


# --------------------------------------------------------------------------- #
# Contract frontend: ma tran quyen phai trung khop hai dau
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_TYPES = REPO_ROOT / "frontend/src/types/api.ts"
FRONTEND_SCOPES = REPO_ROOT / "frontend/src/lib/scopes.ts"
FRONTEND_SCOPES_TEST = REPO_ROOT / "frontend/src/lib/scopes.test.ts"
FRONTEND_APP = REPO_ROOT / "frontend/src/App.tsx"


def _frontend(path: Path) -> str:
    assert path.exists(), f"Khong thay {path.relative_to(REPO_ROOT)} - frontend da doi cau truc thu muc"
    return path.read_text(encoding="utf-8")


def _union(source: str, type_name: str, path: Path) -> set[str]:
    """Doc cac gia tri cua `export type X = 'a' | 'b' | ...;`."""
    match = re.search(rf"export type {type_name}\s*=\s*(.*?);", source, re.DOTALL)
    assert match, f"Khong thay `export type {type_name}` trong {path.name}"
    return set(re.findall(r"'([A-Za-z0-9_]+)'", match.group(1)))


def test_frontend_role_scope_khop_backend() -> None:
    """`Role`/`Scope` va ban sao ma tran quyen ben TS phai trung khop backend that.

    `scopes.test.ts` giu mot BAN SAO cua `ROLE_SCOPES` de test menu ma khong can khoi dong
    backend; ban sao do khong duoc TypeScript kiem tra cheo vi no la `Record<Role, Scope[]>`
    hop le voi bat ky gia tri nao. Lech thi menu hien tab ma API tu choi (hoac nguoc lai:
    API mo ma khong co duong vao).
    """
    types = _frontend(FRONTEND_TYPES)
    assert _union(types, "Role", FRONTEND_TYPES) == {role.value for role in Role}
    assert _union(types, "Scope", FRONTEND_TYPES) == set(ALL_SCOPES)

    test_source = _frontend(FRONTEND_SCOPES_TEST)
    copied_all = re.search(r"const ALL_SCOPES: Scope\[\] = \[(.*?)\];", test_source, re.DOTALL)
    assert copied_all, "Khong thay `const ALL_SCOPES` trong scopes.test.ts - fixture da doi ten"
    assert set(re.findall(r"'([a-z_]+)'", copied_all.group(1))) == set(ALL_SCOPES)

    block = re.search(r"const ROLE_SCOPES: Record<Role, Scope\[\]> = \{(.*?)\n\};", test_source, re.DOTALL)
    assert block, "Khong thay `const ROLE_SCOPES` trong scopes.test.ts - fixture da doi ten"

    for role, expected in ROLE_SCOPES.items():
        # Bat buoc giu dung mot dong cho moi vai: regex duoi day khong bat duoc fixture viet
        # trai nhieu dong. Bao loi con hon la am tham bo qua mot vai tro roi test van xanh.
        line = re.search(rf"^\s*{re.escape(role)}:\s*(.+?),?\s*$", block.group(1), re.MULTILINE)
        assert line, f"scopes.test.ts phai co dung mot dong khai bao cho vai {role}"
        raw = line.group(1).strip()
        copied = list(ALL_SCOPES) if raw == "ALL_SCOPES" else re.findall(r"'([a-z_]+)'", raw)
        assert set(copied) == set(expected), (
            f"{role}: scopes.test.ts cap {sorted(set(copied))} nhung backend cap {sorted(expected)}"
        )


def test_frontend_routes_khop_router_that() -> None:
    """Tab trong NavBar phai khop 1-1 voi route that trong `App.tsx`.

    Thua thi NavBar hien tab dan thang toi NotFoundPage; thieu thi page viet ra khong co
    duong vao. `PAGED_SCOPES` ben TS cung phai dung bang tap route do de bat invariant
    "moi vai con it nhat mot tab" khong bi vo nghia hoa.
    """
    declared = re.findall(r"\{\s*path:\s*'(/[^']+)'[^\n]*?scope:\s*'([a-z_]+)'", _frontend(FRONTEND_SCOPES))
    routed = re.findall(r'path="(/[^"]+)"\s+element=\{\s*<RequireScope scope="([a-z_]+)"', _frontend(FRONTEND_APP))

    assert declared, "Khong doc duoc ROUTES trong scopes.ts - dinh dang da doi"
    assert routed, "Khong doc duoc RequireScope trong App.tsx - dinh dang da doi"
    assert declared == routed, f"ROUTES {declared} lech voi App.tsx {routed}"
    assert {scope for _, scope in declared} <= set(ALL_SCOPES)


def test_username_demo_suy_ra_duoc_tu_ten_vai() -> None:
    """`LoginPage.tsx` khong liet ke tay nua ma sinh username = ten vai viet thuong.

    Doi quy uoc dat ten o `DEMO_USERS` ma khong sua frontend thi nut bam dien ten dang nhap
    se dien mot tai khoan khong ton tai - nguoi dung bam va nhan 401 ma khong hieu vi sao.
    """
    for username, role, _, _ in DEMO_USERS:
        assert username == role.value.lower(), f"{username} phai la {role.value.lower()}"


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
