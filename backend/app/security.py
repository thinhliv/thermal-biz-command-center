"""Bao mat: bcrypt + JWT + RBAC 3 vai, va API key cho endpoint may-goi-may.

Phan quyen theo yeu cau:
- BGD      : thay tat ca
- VANHANH  : chi Nhiet + canh bao (doc & xac nhan)
- KETOAN   : chi Kinh doanh + Cong no
"""

from __future__ import annotations

import hmac
from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
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
# Ban do quyen cho frontend biet nen an/hien tab nao (L1-L10 Enterprise Matrix)
# --------------------------------------------------------------------------- #
ROLE_SCOPES: dict[str, list[str]] = {
    # 3 Vai tro goc (Tuong thich nguoc 100%)
    Role.BGD.value: ["overview", "thermal", "business", "debts", "alerts", "audit"],
    Role.VANHANH.value: ["thermal", "alerts"],
    Role.KETOAN.value: ["business", "debts"],

    # Cap Lanh Dao & Chien Luoc
    Role.L1_CHAIRMAN.value: ["overview", "thermal", "business", "debts", "alerts", "audit"],
    Role.L2_CEO.value: ["overview", "thermal", "business", "debts", "alerts", "audit"],

    # Cap Quan Ly Ky Thuat & Co Dien Lanh
    Role.L3_TECHNICAL_DIRECTOR.value: ["overview", "thermal", "alerts", "audit"],
    Role.L4_OPERATIONS_MANAGER.value: ["thermal", "alerts"],
    Role.L5_MAINTENANCE_ENGINEER.value: ["thermal", "alerts"],

    # Cap Van Hanh Chuoi Kho Lanh & HACCP
    Role.L6_HACCP_AUDITOR.value: ["overview", "thermal", "alerts"],
    Role.L7_WAREHOUSE_DISPATCHER.value: ["thermal", "alerts"],

    # Cap Tai Chinh, Ke Toan & Kinh Doanh ESCO
    Role.L8_CFO.value: ["overview", "business", "debts", "audit"],
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
AuditRoles = require_roles(
    Role.BGD,
    Role.L1_CHAIRMAN,
    Role.L2_CEO,
    Role.L3_TECHNICAL_DIRECTOR,
    Role.L8_CFO,
)
AnyRole = require_roles(*list(Role))
