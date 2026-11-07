"""Fixtures cho test backend.

DB rieng (SQLite in-memory) va secret rieng: test KHONG doc .env cua dev,
vi config.py dung load_dotenv(override=False) nen bien dat o day thang .env.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-only-jwt-secret-key-0123456789abcdef"
os.environ["CONNECTOR_API_KEY"] = "test-connector-api-key"
os.environ["SERVICE_RATE_PER_KWH"] = "3500"
os.environ["AUTO_SEED"] = "false"
os.environ["SEED_DEMO_PASSWORD"] = "TestPass!2026"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import DEMO_USERS, RANDOM_SEED, seed_if_empty, seed_tariff_bands  # noqa: E402


@pytest.fixture()
def session() -> Iterator[Session]:
    """Mot session tren DB sach cho moi test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    s: Session = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def seeded(session: Session) -> Session:
    """Session da co du lieu mau day du (dung seed that, khong fake)."""
    seed_if_empty(session)
    session.commit()
    return session


@pytest.fixture()
def tariff(session: Session) -> Session:
    """Chi nap bieu gia EVN - du cho test billing va nhanh hon nhieu so voi seed day du.

    Co y KHONG nap thiet bi/lich su hoa don: test build_invoice can mot ky sach
    de kiem tra idempotency that su.
    """
    seed_tariff_bands(session)
    session.commit()
    return session


@pytest.fixture()
def client(session: Session) -> TestClient:
    """TestClient KHONG chay lifespan.

    Co y khong dung `with TestClient(...)`: lifespan goi dispose() se dong ket noi
    SQLite in-memory dung chung (StaticPool), lam hong cac test sau. DB do fixture
    `session` chuan bi, AUTO_SEED=false nen cung khong can lifespan seed.
    """
    return TestClient(app)


@pytest.fixture()
def seeded_client(seeded: Session) -> TestClient:
    return TestClient(app)


def login(client: TestClient, username: str, password: str = "TestPass!2026") -> str:
    """Tra ve access token. Mat khau lay tu DEMO_USERS cua seed."""
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tokens(seeded_client: TestClient) -> dict[str, str]:
    """Token cho ca 3 vai, khoa bang username trong DEMO_USERS."""
    return {role.value: login(seeded_client, username) for username, role, _, _ in DEMO_USERS}


@pytest.fixture()
def rng_seed() -> int:
    return RANDOM_SEED
