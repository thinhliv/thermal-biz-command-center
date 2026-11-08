"""Bao mat: bcrypt + JWT + RBAC, va API key cho endpoint may-goi-may.

Hai tang vai tro song song (xem `Role` trong models.py):
- 3 vai goc, tuong thich nguoc voi phien ban dau:
    BGD      : thay tat ca
    VANHANH  : chi Nhiet + canh bao (doc & xac nhan)
    KETOAN   : chi Kinh doanh + Cong no
- L1-L10 Enterprise Matrix: phan quyen chi tiet theo tung khoi (lanh dao / ky thuat /
  chat luong HACCP / tai chinh - kinh doanh).

Endpoint bao ve bang cac bundle `require_roles(...)` o cuoi file; con `ROLE_SCOPES` chi
dung de frontend an/hien tab va cat ban tin WebSocket. Chieu bat buoc: moi scope cua mot
vai tro phai duoc mot bundle cho phep, neu khong tab hien ra nhung moi loi goi deu 403.
Chieu nguoc lai (co bundle ma khong co scope) thi hop le va co y: API mo cho vai tro do
nhung UI khong dung tab rieng. Ba vai goc giu dung pham vi tab theo yeu cau nghiep vu
(VANHANH chi Nhiet + Canh bao, KETOAN chi Kinh doanh + Cong no) du ho van goi duoc
/api/ai va /api/compliance tu cac man hinh khac.
"""

from __future__ import annotations

import hmac
from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_session
from .models import Role, User
from .timeutil import utcnow

# bcrypt chi bam duoc 72 byte dau; chan som de nguoi dung biet mat khau bi cat ngam
BCRYPT_MAX_BYTES = 72

_bearer = HTTPBearer(auto_error=False)

CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Khong xac thuc duoc. Hay dang nhap lai.",
    headers={"WWW-Authenticate": "Bearer"},
)


# --------------------------------------------------------------------------- #
# Mat khau
# --------------------------------------------------------------------------- #
def hash_password(plain: str) -> str:
    raw = plain.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Mat khau toi da {BCRYPT_MAX_BYTES} byte (bcrypt gioi han), dang nhap {len(raw)} byte.")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        raw = plain.encode("utf-8")[:BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_access_token(user: User, expire_minutes: int | None = None) -> tuple[str, int]:
    settings = get_settings()
    expires_in = expire_minutes or settings.jwt_expire_minutes
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
        "iat": now,
        "exp": now + timedelta(minutes=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phien dang nhap het han.") from exc
    except jwt.InvalidTokenError as exc:
        raise CREDENTIALS_EXC from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise CREDENTIALS_EXC
    payload = decode_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CREDENTIALS_EXC from exc

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise CREDENTIALS_EXC
    # Token cu khong con hieu luc neu vai tro da bi thay doi
    if user.role != payload.get("role"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Vai tro cua ban da thay doi. Hay dang nhap lai.",
        )
    return user


def require_roles(*roles: Role):
    """Dependency factory: chi cho phep cac vai tro duoc liet ke."""
    allowed = {r.value for r in roles}

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Vai tro '{user.role}' khong co quyen truy cap tai nguyen nay.",
            )
        return user

    return _guard


# --------------------------------------------------------------------------- #
# API key cho connector (may goi may, khong dung JWT)
# --------------------------------------------------------------------------- #
def require_connector_key(x_connector_api_key: str = Header(default="")) -> None:
    settings = get_settings()
    if not settings.connector_api_key:
        # Khong de endpoint nay mo khi chua cau hinh key
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CONNECTOR_API_KEY chua duoc cau hinh po backend. Tu choi nhan du lieu.",
        )
    if not hmac.compare_digest(x_connector_api_key, settings.connector_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Connector API key khong hop le.")


# --------------------------------------------------------------------------- #
# Dia chi nguon goi (de ghi vao nhat ky kiem toan)
# --------------------------------------------------------------------------- #
def client_ip(request: Request) -> str | None:
    """Dia chi IP cua ben goi, lay tu ket noi TCP that.

    KHONG doc X-Forwarded-For: header do do client tu dat nen ai cung gia mao duoc,
    ma nhat ky kiem toan dung IP de truy nguon - ghi vao mot gia tri gia mao duoc thi
    cot do vo dung, con nguy hon la de trong vi nguoi doc tuong no dang tin.

    He qua phai noi ro: khi chay sau reverse proxy (nginx/traefik) moi ban ghi deu mang
    IP cua proxy. Muon co IP that thi phai them cau hinh "chi tin header den tu proxy
    nao" - khong duoc tin XFF vo dieu kien.
    """
    return request.client.host if request.client else None


# --------------------------------------------------------------------------- #
# Ban do quyen cho frontend biet nen an/hien tab nao (L1-L10 Enterprise Matrix)
# --------------------------------------------------------------------------- #
#: Moi scope ma frontend biet ve. Them scope moi thi phai them o day VA o
#: `frontend/src/types/api.ts` (type `Scope`), neu khong hai ben lech nhau am tham.
ALL_SCOPES: list[str] = [
    "overview",
    "thermal",
    "alerts",
    "business",
    "debts",
    "audit",
    "compliance",
    "ai",
    "sync",
]

#: Scope phai phu het moi pillar co endpoint, neu khong frontend khong the an/hien tab
#: tuong ung va se goi API ma chac chan nhan 403. Truoc day chi co 6 scope cua pillar 1
#: (overview/thermal/business/debts/alerts/audit) trong khi backend da co them
#: /api/sync, /api/ai, /api/compliance -> ba pillar do vo hinh tren UI.
ROLE_SCOPES: dict[str, list[str]] = {
    # 3 Vai tro goc (Tuong thich nguoc 100%)
    Role.BGD.value: ALL_SCOPES,
    Role.VANHANH.value: ["thermal", "alerts"],
    Role.KETOAN.value: ["business", "debts"],

    # Cap Lanh Dao & Chien Luoc
    Role.L1_CHAIRMAN.value: ALL_SCOPES,
    Role.L2_CEO.value: ALL_SCOPES,

    # Cap Quan Ly Ky Thuat & Co Dien Lanh
    Role.L3_TECHNICAL_DIRECTOR.value: ["overview", "thermal", "alerts", "audit", "ai", "sync"],
    Role.L4_OPERATIONS_MANAGER.value: ["thermal", "alerts", "sync"],
    Role.L5_MAINTENANCE_ENGINEER.value: ["thermal", "alerts", "ai"],

    # Cap Van Hanh Chuoi Kho Lanh & HACCP
    # L6 la vai tro CHUYEN KIEM TOAN: phai co `compliance` (bao cao HACCP/ESG) va `audit`
    # (nhat ky hanh vi + xac minh chuoi bam). Thieu hai scope nay thi vai tro sinh ra de
    # kiem toan khong kiem toan duoc gi ca.
    Role.L6_HACCP_AUDITOR.value: ["overview", "thermal", "alerts", "compliance", "audit"],
    Role.L7_WAREHOUSE_DISPATCHER.value: ["thermal", "alerts"],

    # Cap Tai Chinh, Ke Toan & Kinh Doanh ESCO
    # L8 co `compliance` vi bao cao phat thai ESG Scope 1 & 2 la nghia vu cong bo cua CFO.
    Role.L8_CFO.value: ["overview", "business", "debts", "audit", "compliance"],
    Role.L9_BILLING_SPECIALIST.value: ["business", "debts"],
    Role.L10_SALES_EXECUTIVE.value: ["business"],
}


def scopes_for(role: str) -> list[str]:
    return list(ROLE_SCOPES.get(role, []))


# Dependency dung lai cho cac router ho tro toan bo L1-L10
ExecutiveOnly = require_roles(Role.BGD, Role.L1_CHAIRMAN, Role.L2_CEO)
ThermalRoles = require_roles(
    Role.BGD,
    Role.VANHANH,
    Role.L1_CHAIRMAN,
    Role.L2_CEO,
    Role.L3_TECHNICAL_DIRECTOR,
    Role.L4_OPERATIONS_MANAGER,
    Role.L5_MAINTENANCE_ENGINEER,
    Role.L6_HACCP_AUDITOR,
    Role.L7_WAREHOUSE_DISPATCHER,
)
FinanceRoles = require_roles(
    Role.BGD,
    Role.KETOAN,
    Role.L1_CHAIRMAN,
    Role.L2_CEO,
    Role.L8_CFO,
    Role.L9_BILLING_SPECIALIST,
    Role.L10_SALES_EXECUTIVE,
)
# Them L6_HACCP_AUDITOR: nguoi phat hanh chung chi HACCP (`POST /api/compliance/haccp/
# certificate`) ma khong doc duoc nhat ky kiem toan thi vai tro do khong lam duoc viec.
AuditRoles = require_roles(
    Role.BGD,
    Role.L1_CHAIRMAN,
    Role.L2_CEO,
    Role.L3_TECHNICAL_DIRECTOR,
    Role.L6_HACCP_AUDITOR,
    Role.L8_CFO,
)
#: Doc bao cao HACCP / dau chan carbon ESG. Khong dung `AnyRole`: L9 (billing) va L10
#: (kinh doanh) khong co ly do nghiep vu nao de xem so lan vi pham nguong nhiet do.
#: KETOAN co quyen doc ESG vi dau chan carbon la chi phi phai cong bo va tinh gia thanh.
ComplianceRoles = require_roles(
    Role.BGD,
    Role.KETOAN,
    Role.L1_CHAIRMAN,
    Role.L2_CEO,
    Role.L3_TECHNICAL_DIRECTOR,
    Role.L4_OPERATIONS_MANAGER,
    Role.L6_HACCP_AUDITOR,
    Role.L8_CFO,
)
#: Lich cat dinh phu tai & chan doan bao tri du doan: cong cu cua khoi ky thuat, cua cap
#: dieu hanh / tai chinh vi no quyet dinh chi phi dien, va cua truong ca van hanh vi
#: nguoi do la nguoi thuc thi lich cat tai tren san.
AiRoles = require_roles(
    Role.BGD,
    Role.VANHANH,
    Role.L1_CHAIRMAN,
    Role.L2_CEO,
    Role.L3_TECHNICAL_DIRECTOR,
    Role.L4_OPERATIONS_MANAGER,
    Role.L5_MAINTENANCE_ENGINEER,
    Role.L8_CFO,
)
AnyRole = require_roles(*list(Role))
