"""Pre-flight check cho `docker compose up`, gom 2 viec:

1. Moi bien ${VAR} / ${VAR:?msg} trong compose va Grafana provisioning phai ton tai trong
   .env (tru khi no co gia tri mac dinh ${VAR:-default}).
2. Moi bien ma file datasource Grafana noi suy phai duoc forward vao `environment:` cua
   service `grafana` cung stack. Grafana doc ${VAR} tu moi truong cua chinh container no,
   khong phai tu .env cua host - nen mot bien "co trong .env" van chua du.

Dung truoc khi `docker compose up` de biet thieu bien nao, thay vi de Docker bao loi mo ho.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    "docker-compose.yml",
    "docker/docker-compose.enterprise.yml",
    "docker/docker-compose.lightweight.yml",
    # Moi stack mot file datasource rieng (Grafana mount tung file, khong mount ca thu muc),
    # nen phai quet ca ba. Quet thieu file nao thi stack do len voi password rong.
    "grafana/provisioning/datasources/app.yaml",
    "grafana/provisioning/datasources/enterprise.yaml",
    "grafana/provisioning/datasources/lightweight.yaml",
]

# ${NAME} | ${NAME:?msg} | ${NAME?msg} | ${NAME:-default} | ${NAME-default}
VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])([^}]*))?\}")

COMMENT_RE = re.compile(r"^\s*#")

# Moi stack: file compose + file datasource Grafana ma stack do mount.
GRAFANA_STACKS = [
    ("docker-compose.yml", "grafana/provisioning/datasources/app.yaml"),
    ("docker/docker-compose.enterprise.yml", "grafana/provisioning/datasources/enterprise.yaml"),
    ("docker/docker-compose.lightweight.yml", "grafana/provisioning/datasources/lightweight.yaml"),
]

ENV_VALUE_KEY_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*:")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def scan(path: Path) -> list[tuple[int, str, bool]]:
    """Tra ve [(so_dong, ten_bien, co_default)]."""
    found = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if COMMENT_RE.match(line):
            continue
        for match in VAR_RE.finditer(line):
            operator = match.group(2)
            has_default = operator is not None and operator.endswith("-")
            found.append((lineno, match.group(1), has_default))
    return found


def grafana_env_keys(compose_path: Path) -> set[str]:
    """Cac bien duoc forward vao `environment:` cua service `grafana` trong mot file compose.

    Doc bang text (khong dung PyYAML) vi script nay phai chay duoc bang python he thong
    luc nguoi dung chua dung venv.
    """
    keys: set[str] = set()
    in_grafana = False
    in_environment = False

    for line in compose_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())

        if indent < 2:  # services: / volumes: / networks: -> het khoi service
            in_grafana = False
            in_environment = False
        elif indent == 2:  # ten service
            in_grafana = stripped == "grafana:"
            in_environment = False
        elif in_grafana and indent == 4:
            in_environment = stripped == "environment:"
        elif in_grafana and in_environment and indent == 6:
            match = ENV_VALUE_KEY_RE.match(stripped)
            if match:
                keys.add(match.group(1))

    return keys


def find_grafana_env_gaps_with_stacks(
    repo_root: Path, stacks: list[tuple[str, str]]
) -> list[str]:
    """Bien dung trong datasource YAML nhung khong duoc forward vao container grafana.

    Grafana noi suy ${VAR} trong file provisioning TU MOI TRUONG CUA CHINH NO, khong phai
    tu .env cua host. Bien thieu duoc thay bang chuoi rong: datasource van provision
    "thanh cong" (Grafana khong xac thuc ket noi luc provision) nhung database/user rong,
    nen chi lo ra khi nguoi dung mo panel va thay loi query. `docker compose config` cung
    khong canh bao, vi doi voi compose thi day van la mot bien moi truong hop le.
    """
    gaps: list[str] = []
    for compose_relative, datasource_relative in stacks:
        compose_path = repo_root / compose_relative
        datasource_path = repo_root / datasource_relative
        if not compose_path.exists() or not datasource_path.exists():
            continue

        forwarded = grafana_env_keys(compose_path)
        for lineno, name, _has_default in scan(datasource_path):
            if name not in forwarded:
                gaps.append(
                    f"{datasource_relative}:{lineno}  {name}"
                    f"  -> thieu trong environment: cua service `grafana` ({compose_relative})"
                )
    return gaps


def find_grafana_env_gaps(repo_root: Path) -> list[str]:
    return find_grafana_env_gaps_with_stacks(repo_root, GRAFANA_STACKS)


def main() -> int:
    # Chay truoc ca viec doi .env: loi nay khong phu thuoc .env, va neu dung o day thi
    # nguoi dung van phai nhin thay no thay vi chi thay "thieu .env".
    grafana_gaps = find_grafana_env_gaps(REPO_ROOT)
    if grafana_gaps:
        print("[LOI] Bien trong datasource Grafana KHONG duoc forward vao container grafana:")
        print("      Grafana noi suy ${VAR} tu moi truong cua chinh no, khong phai tu .env cua host.")
        print("      Thieu bien -> datasource provision voi database/user rong, moi panel deu loi query.")
        for item in grafana_gaps:
            print(f"      - {item}")

    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        print("[LOI] Khong tim thay .env o goc repo.")
        print("      Chay: Copy-Item .env.example .env  roi dien gia tri.")
        return 1

    env = load_env(env_path)
    missing: list[str] = []
    empty_required: list[str] = []

    for relative in TARGETS:
        path = REPO_ROOT / relative
        if not path.exists():
            continue
        for lineno, name, has_default in scan(path):
            if name not in env:
                if not has_default:
                    missing.append(f"{relative}:{lineno}  {name}")
            elif not env[name] and not has_default:
                empty_required.append(f"{relative}:{lineno}  {name}")

    ok = not grafana_gaps

    if missing:
        ok = False
        print("[LOI] Cac bien sau duoc dung nhung KHONG co trong .env va KHONG co gia tri mac dinh:")
        for item in sorted(set(missing)):
            print(f"      - {item}")

    if empty_required:
        print("[CANH BAO] Cac bien sau co trong .env nhung dang RONG va khong co gia tri mac dinh.")
        print("            Docker se khoi dong duoc, nhung service lien quan se fail-fast khi chay:")
        for item in sorted(set(empty_required)):
            print(f"      - {item}")

    if ok:
        print(f"[OK] .env day du cho {len(TARGETS)} file cau hinh ({len(env)} bien),")
        print(f"     va ca {len(GRAFANA_STACKS)} Grafana deu duoc forward du bien datasource.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
