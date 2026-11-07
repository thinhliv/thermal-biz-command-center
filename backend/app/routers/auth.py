"""Dang nhap, thong tin nguoi dung, doi mat khau."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..models import User
from ..schemas import ChangePasswordRequest, LoginRequest, LoginResponse, UserPublic
from ..security import (
    create_access_token,
    get_current_user,
    hash_password,
    scopes_for,
    verify_password,
)
from ..timeutil import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Hash gia de luon ton thoi gian bcrypt nhu nhau, tranh lo ten nguoi dung qua thoi gian phan ung
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalisation-0")


def _public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        scopes=scopes_for(user.role),
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> LoginResponse:
    user = session.scalars(select(User).where(User.username == payload.username)).first()
    hashed = user.password_hash if user else _DUMMY_HASH
    password_ok = verify_password(payload.password, hashed)

    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tên đăng nhập hoặc mật khẩu.",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tài khoản đã bị khóa.")

    token, expires_in = create_access_token(user)
    user.last_login_at = utcnow()
    session.commit()
    return LoginResponse(access_token=token, expires_in_minutes=expires_in, user=_public(user))


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)) -> UserPublic:
    return _public(user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mat khau hien tai khong dung.")
    try:
        user.password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
