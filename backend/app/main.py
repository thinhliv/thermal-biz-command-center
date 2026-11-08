"""Executive Command Center - FastAPI backend.

Thermal Engineering x Business Administration.

Khong con du lieu mock: moi con so deu doc tu DB (SQLite khi dev, Postgres khi prod).
Doi `DATABASE_URL` trong `.env` la doi backend, khong sua code.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal, create_all, dispose
from .models import Role, User
from .routers import ai, alerts, audit, auth, business, compliance, dashboard, debts, ingest, sync, thermal
from .schemas import HealthResponse
from .security import scopes_for
from .seed import seed_if_empty
from .services import billing, thermal as thermal_service
from .timeutil import day_bounds, utcnow

logger = logging.getLogger("command-center")

settings = get_settings()


def _bootstrap() -> dict:
    """Chuan bi DB luc khoi dong. Tra ve thong ke de log.

    SQLite (dev/test): tu tao bang de chay duoc ma khong can cai dat gi.
    Postgres (prod): schema do Alembic quan ly, entrypoint da chay `alembic upgrade head`.
    Goi `create_all()` o prod se tao bang ma khong stamp alembic_version -> lan
    migrate sau chay lai migration dau va fail vi bang da ton tai.
    """
    if settings.is_sqlite:
        create_all()
    session: Session = SessionLocal()
    try:
        if settings.auto_seed:
            return seed_if_empty(session)
        return {"seeded": False, "reason": "AUTO_SEED=false"}
    finally:
        session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Backend %s - schema quan ly boi %s",
        "sqlite" if settings.is_sqlite else "postgres",
        "create_all() khi khoi dong" if settings.is_sqlite else "Alembic (entrypoint)",
    )
    stats = _bootstrap()
    if stats.get("seeded"):
        logger.info("Da seed du lieu khoi tao: %s", {k: v for k, v in stats.items() if k != "seeded"})
    else:
        logger.info("Bo qua seed: %s", stats.get("reason"))
    yield
    dispose()


app = FastAPI(
    title="Thermal & Business Command Center API",
    description=(
        "API thoi gian thuc ket hop ky thuat nhiet lanh va quan tri kinh doanh. "
        "Xac thuc JWT, phan quyen 13 vai (BGD / VANHANH / KETOAN + ma tran L1-L10). "
        "Endpoint /api/ingest/* danh cho connector, khoa bang X-Connector-Api-Key."
    ),
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Khong dung "*" vi allow_credentials=True: trinh duyet se chan va lo luon du lieu.
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Connector-Api-Key"],
)

for module in (auth.router, dashboard.router, thermal.router, business.router, debts.router, alerts.router, ingest.router, audit.router, sync.router, ai.router, compliance.router):
    app.include_router(module)


@app.get("/api/health", tags=["system"], response_model=HealthResponse)
def health_check() -> dict:
    """Khong xac thuc - dung cho Docker/K8s healthcheck."""
    session: Session = SessionLocal()
    try:
        error = None
        try:
            session.connection()
        except Exception as exc:  # pragma: no cover - chi xay ra khi DB chet
            error = str(exc)
    finally:
        session.close()

    return {
        "status": "ok" if error is None else "degraded",
        "database": "ok" if error is None else f"error: {error}",
        "system": settings.app_name,
        "version": settings.version,
        "backend": "sqlite" if settings.is_sqlite else "postgres",
    }


@app.get("/api/system/config", tags=["system"])
def public_config() -> dict:
    """Cau hinh frontend can de ve UI. KHONG tra ve secret."""
    return {
        "app_name": settings.app_name,
        "version": settings.version,
        "roles": [role.value for role in Role],
        "scopes": {role.value: scopes_for(role.value) for role in Role},
        "ws_interval_seconds": settings.telemetry_ws_interval_seconds,
        "vibration_limit_mm_s": thermal_service.VIBRATION_ISO10816_LIMIT_MM_S,
        "haccp_seafood_limit_c": thermal_service.HACCP_SEAFOOD_LIMIT_C,
    }


# --------------------------------------------------------------------------- #
# WebSocket telemetry
# --------------------------------------------------------------------------- #
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket) -> None:
    """Day ban nhe (Nhiet + canh bao) theo chu ky.

    WebSocket cua trinh duyet khong gui duoc header Authorization nen token
    truyen qua query string `?token=`. Van phai xac thuc: khong de stream mo.
    """
    token = websocket.query_params.get("token", "")
    user = _authenticate_ws(token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    scopes = set(scopes_for(user.role))
    if not (scopes & {"thermal", "alerts"}):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    interval = max(1.0, settings.telemetry_ws_interval_seconds)
    try:
        while True:
            payload = _ws_snapshot(scopes)
            await websocket.send_json(payload)
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return
    except RuntimeError:
        # Socket da bi dong tu phia client
        return


def _authenticate_ws(token: str) -> User | None:
    """Xac thuc token cho WebSocket. Tra ve None neu sai/het han/vai tro da doi."""
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None

    session: Session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if user is None:
            return None
        # Doc het thuoc tinh can dung TRUOC khi dong session
        return user if (user.is_active and user.role == payload.get("role")) else None
    finally:
        session.close()


def _ws_snapshot(scopes: set[str]) -> dict:
    session: Session = SessionLocal()
    try:
        summary = thermal_service.summarize_thermal(session)
        payload: dict = {}
        if "thermal" in scopes:
            payload["thermal_summary"] = summary
        if "alerts" in scopes:
            payload["alerts"] = summary["alerts"]
        if "business" in scopes:
            # Chi tinh them khi vai tro duoc xem, tranh tinh thua cho van hanh
            today_start, today_end = day_bounds(utcnow())
            payload["energy"] = billing.energy_cost_report(session, today_start, today_end)
        return payload
    finally:
        session.close()
