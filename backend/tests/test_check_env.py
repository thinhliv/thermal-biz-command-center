"""Test cho scripts/check_env.py - cong pre-flight ma run.ps1 bat buoc phai xanh.

Script nay tung chi kiem tra "bien co trong .env hay khong", nen bo lot hai loi that:

1. Datasource Grafana doi hoi TB_DB_NAME / TB_DB_USER / ERP_DB_NAME / ERP_DB_USER (stack A)
   va NINJA_DB_NAME / NINJA_DB_USER (stack B), nhung compose chi forward password. Grafana
   noi suy ${VAR} tu moi truong cua chinh container no, khong phai tu .env cua host -> bien
   thieu thanh chuoi rong, datasource van provision "thanh cong" voi database/user rong va
   moi panel deu loi query. `docker compose config` khong canh bao vi day van la bien hop le.

2. Grafana cua stack A dung lai GRAFANA_PORT (3000) cua stack ung dung, trong khi stack A
   bat buoc chay song song voi stack ung dung -> "port is already allocated".

Ca hai deu vo hinh tren CI nen phai co test giu.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("check_env", REPO_ROOT / "scripts" / "check_env.py")
check_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_env)

COMPOSE_FILES = [
    "docker-compose.yml",
    "docker/docker-compose.enterprise.yml",
    "docker/docker-compose.lightweight.yml",
]

# - "${VAR:-5433}:5432" | - "${VAR:?msg}:8080" | - "${VAR:-5683}:5683/udp" | - "3000:3000"
PORT_RE = re.compile(r'^\s*-\s*"(?P<host>\$\{[^}]*\}|\d+):(?P<container>\d+)(?:/\w+)?\s*"')
HOST_VAR_RE = re.compile(r"^\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<rest>[^}]*)\}")


def _env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _default_of(var: re.Match[str]) -> str | None:
    """Gia tri mac dinh cua ${VAR:-default}; None voi ${VAR} va ${VAR:?msg}."""
    rest = var.group("rest")
    return rest[2:] if rest.startswith(":-") else None


def _published_ports() -> dict[str, list[tuple[str, str]]]:
    """{port_host: [(file_compose, bien)]} tinh theo gia tri mac dinh trong .env.example."""
    example = _env_example()
    found: dict[str, list[tuple[str, str]]] = {}
    for relative in COMPOSE_FILES:
        for line in (REPO_ROOT / relative).read_text(encoding="utf-8").splitlines():
            match = PORT_RE.match(line)
            if not match:
                continue
            host_spec = match.group("host")
            var = HOST_VAR_RE.match(host_spec)
            if var:
                host = _default_of(var) or example.get(var.group("name"))
                label = var.group("name")
            else:
                host, label = host_spec, host_spec
            if host is None:
                continue
            found.setdefault(host, []).append((relative, label))
    return found


def test_moi_bien_datasource_deu_duoc_forward_vao_container_grafana():
    gaps = check_env.find_grafana_env_gaps(REPO_ROOT)
    assert not gaps, f"Grafana thieu bien datasource: {gaps}"


def test_check_env_bat_duoc_bien_khong_duoc_forward(tmp_path: Path):
    """Lap lai dung loi tung lot: datasource doi hoi bien ma compose khong forward."""
    (tmp_path / "docker").mkdir()
    (tmp_path / "grafana").mkdir()
    (tmp_path / "docker" / "compose.yml").write_text(
        "services:\n"
        "  db:\n"
        "    environment:\n"
        "      DB_NAME: ${DB_NAME:-app}\n"
        "  grafana:\n"
        "    environment:\n"
        "      DB_PASSWORD: ${DB_PASSWORD:?required}\n",
        encoding="utf-8",
    )
    (tmp_path / "grafana" / "ds.yaml").write_text(
        "datasources:\n"
        "  - name: App DB\n"
        "    database: ${DB_NAME}\n"
        "    secureJsonData:\n"
        "      password: ${DB_PASSWORD}\n",
        encoding="utf-8",
    )

    gaps = check_env.find_grafana_env_gaps_with_stacks(
        tmp_path, [("docker/compose.yml", "grafana/ds.yaml")]
    )

    assert gaps == [
        "grafana/ds.yaml:3  DB_NAME"
        "  -> thieu trong environment: cua service `grafana` (docker/compose.yml)"
    ]


def test_grafana_env_keys_chi_lay_service_grafana(tmp_path: Path):
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n"
        "  db:\n"
        "    environment:\n"
        "      POSTGRES_PASSWORD: x\n"
        "  grafana:\n"
        "    image: grafana/grafana:latest\n"
        "    environment:\n"
        "      GF_USERS_DEFAULT_THEME: dark\n"
        "      TB_DB_NAME: ${TB_DB_NAME:-thingsboard}\n"
        "    volumes:\n"
        "      - ./x.yaml:/etc/grafana/x.yaml:ro\n"
        "  connector:\n"
        "    environment:\n"
        "      API_KEY: y\n"
        "volumes:\n"
        "  some_volume:\n",
        encoding="utf-8",
    )
    assert check_env.grafana_env_keys(compose) == {"GF_USERS_DEFAULT_THEME", "TB_DB_NAME"}


def test_khong_hai_stack_nao_cung_bind_mot_port_host():
    """Ba stack duoc tai lieu hoa la chay song song, nen port host phai doi mot.

    Grafana cua stack A tung dung lai GRAFANA_PORT (3000) cua stack ung dung -> docker bao
    "port is already allocated" ngay luc `up`, va thong bao do khong he chi ra ai giu port.
    """
    conflicts = {port: where for port, where in _published_ports().items() if len(where) > 1}
    assert not conflicts, f"Port host bi trung giua cac stack: {conflicts}"


def test_moi_port_trong_compose_deu_xac_dinh_duoc_gia_tri():
    """Bien port nao cung phai co gia tri mac dinh trong compose hoac trong .env.example.

    Neu khong, test tren se am tham bo qua bien do va loi trung port tro lai ma khong ai biet.
    """
    example = _env_example()
    unresolved: list[str] = []
    for relative in COMPOSE_FILES:
        for lineno, line in enumerate(
            (REPO_ROOT / relative).read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = PORT_RE.match(line)
            if not match:
                continue
            var = HOST_VAR_RE.match(match.group("host"))
            if var and _default_of(var) is None and var.group("name") not in example:
                unresolved.append(f"{relative}:{lineno}  {var.group('name')}")
    assert not unresolved, f"Port khong xac dinh duoc gia tri mac dinh: {unresolved}"
