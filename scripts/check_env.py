"""Pre-flight check: moi bien ${VAR} / ${VAR:?msg} trong compose va Grafana provisioning
phai ton tai trong .env (tru khi no co gia tri mac dinh ${VAR:-default}).

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


def main() -> int:
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

    ok = True

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
        print(f"[OK] .env day du cho {len(TARGETS)} file cau hinh ({len(env)} bien).")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
