"""Cau hinh ung dung doc tu bien moi truong.

Dev mac dinh dung SQLite (khong can cai gi). Doi DATABASE_URL sang
postgresql+psycopg2://... de chuyen sang Postgres ma khong sua code.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

# .env o goc repo (docker compose / dev), fallback backend/.env
for candidate in (REPO_ROOT / ".env", BACKEND_DIR / ".env"):
    if candidate.exists():
        load_dotenv(candidate, override=False)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.app_name: str = os.getenv("APP_NAME", "Thermal & Business Command Center")
        self.version: str = os.getenv("APP_VERSION", "1.0.0")

        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///./thermal_biz.db")
        self.db_echo: bool = _bool("DB_ECHO", False)
        # Alembic can URL rieng (vi du khi chay migration ngoai container)
        self.alembic_database_url: str = os.getenv("ALEMBIC_DATABASE_URL", self.database_url)

        self.jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "")
        self.jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

        self.cors_origins: list[str] = [
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ]

        # Khoa cac endpoint /api/ingest/* cho connector goi vao
        self.connector_api_key: str = os.getenv("CONNECTOR_API_KEY", "")

        # Phi quan ly tinh tren moi kWh khi xuat hoa don cho khach thue kho.
        # Lay tu server, KHONG bao gio nhan tu ben goi.
        self.service_rate_per_kwh: int = int(os.getenv("SERVICE_RATE_PER_KWH", "3500"))

        # Tu seed du lieu mau khi DB rong (tien cho dev/demo)
        self.auto_seed: bool = _bool("AUTO_SEED", True)
        # Co y KHONG co gia tri mac dinh: repo nay public, mot mat khau demo
        # viet san trong code la tai khoan that voi ai doc repo. Thieu -> bao loi cau hinh.
        self.seed_demo_user_password: str = os.getenv("SEED_DEMO_PASSWORD", "")

        self.telemetry_ws_interval_seconds: float = float(os.getenv("TELEMETRY_WS_INTERVAL_SECONDS", "3"))

        self.validate()

    def validate(self) -> None:
        problems: list[str] = []
        if not self.jwt_secret_key:
            problems.append("JWT_SECRET_KEY rong - khong the ky token.")
        elif len(self.jwt_secret_key) < 32:
            problems.append("JWT_SECRET_KEY qua ngan (can >= 32 ky tu).")
        if self.database_url.startswith("sqlite"):
            # sqlite:////abs/path va sqlite:///./rel deu hop le
            pass
        elif "://" not in self.database_url:
            problems.append(f"DATABASE_URL khong hop le: {self.database_url!r}")
        if "*" in self.cors_origins:
            # allow_credentials=True nen "*" se bi Starlette bien thanh "reflect moi origin"
            # -> bat ky trang web nao cung goi duoc API tu trinh duyet cua nan nhan.
            problems.append("CORS_ORIGINS khong duoc chua '*'. Liet ke ro tung origin.")
        if self.auto_seed and len(self.seed_demo_user_password) < 8:
            problems.append(
                "SEED_DEMO_PASSWORD phai co it nhat 8 ky tu khi AUTO_SEED=true "
                "(hoac dat AUTO_SEED=false neu khong muon tao tai khoan demo)."
            )
        if problems:
            raise RuntimeError("Cau hinh backend khong hop le:\n  - " + "\n  - ".join(problems))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
