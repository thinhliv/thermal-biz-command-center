"""Cau hinh phai fail SOM va fail RO.

Repo nay public: mot gia tri mac dinh "tien" trong code (mat khau demo, CORS "*")
la loi bao mat that su, khong phai chuyen tham my. Nhung test nay giu chung khong quay lai.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def _make(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> Settings:
    """Dung Settings() truc tiep (khong qua get_settings da lru_cache) de doc env moi."""
    for key, value in overrides.items():
        if value is None:
            monkeypatch.delenv(key.upper(), raising=False)
        else:
            monkeypatch.setenv(key.upper(), value)
    return Settings()


def test_cau_hinh_hien_tai_hop_le(monkeypatch: pytest.MonkeyPatch):
    """Baseline: neu test nay do thi van de nam o .env/conftest, khong phai o validate()."""
    settings = _make(monkeypatch)
    assert settings.jwt_algorithm == "HS256"


def test_jwt_secret_rong_hoac_ngan_bi_chan(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY rong"):
        _make(monkeypatch, jwt_secret_key="")

    with pytest.raises(RuntimeError, match="qua ngan"):
        _make(monkeypatch, jwt_secret_key="ngan-qua")


def test_cors_wildcard_bi_chan(monkeypatch: pytest.MonkeyPatch):
    """allow_credentials=True + "*" = Starlette reflect moi origin -> CSRF/API hijack."""
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        _make(monkeypatch, cors_origins="http://localhost:5173,*")


def test_cors_nhieu_origin_van_hop_le(monkeypatch: pytest.MonkeyPatch):
    settings = _make(monkeypatch, cors_origins="http://a.test, http://b.test ,")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_khong_co_mat_khau_demo_mac_dinh_trong_code(monkeypatch: pytest.MonkeyPatch):
    """Ai doc repo khong duoc biet mat khau cua tai khoan demo."""
    settings = _make(monkeypatch, seed_demo_password=None, auto_seed="false")
    assert settings.seed_demo_user_password == ""


def test_seed_bat_buoc_khai_mat_khau(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(RuntimeError, match="SEED_DEMO_PASSWORD"):
        _make(monkeypatch, auto_seed="true", seed_demo_password=None)

    with pytest.raises(RuntimeError, match="it nhat 8 ky tu"):
        _make(monkeypatch, auto_seed="true", seed_demo_password="123")


def test_tat_auto_seed_thi_khong_can_mat_khau_demo(monkeypatch: pytest.MonkeyPatch):
    """Prod khong seed -> khong bat phai dat bien khong dung den."""
    assert _make(monkeypatch, auto_seed="false", seed_demo_password=None).auto_seed is False


@pytest.mark.parametrize(
    ("url", "is_sqlite"),
    [
        ("sqlite:///./thermal_biz.db", True),
        ("sqlite:////var/lib/app/thermal.db", True),
        ("postgresql+psycopg2://u:p@db:5432/app", False),
    ],
)
def test_doi_database_url_la_doi_backend_khong_sua_code(
    monkeypatch: pytest.MonkeyPatch, url: str, is_sqlite: bool
):
    """Quyet dinh kien truc: SQLite cho dev, Postgres cho prod, cung mot bo code."""
    settings = _make(monkeypatch, alembic_database_url=None, database_url=url, auto_seed="false")
    assert settings.is_sqlite is is_sqlite
    # Alembic theo DATABASE_URL neu khong khai bao rieng
    assert settings.alembic_database_url == url


def test_database_url_khong_co_scheme_bi_chan(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(RuntimeError, match="DATABASE_URL khong hop le"):
        _make(monkeypatch, database_url="localhost:5432/app", auto_seed="false")
