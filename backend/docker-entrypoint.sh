#!/bin/sh
# Khoi dong container API.
#
# Postgres (prod): schema do Alembic quan ly. Migration chay TRUOC khi uvicorn len
# va `set -e` de container chet ngay neu migrate fail - con hon la phuc vu tren schema sai.
# SQLite (dev): bo qua, lifespan cua app tu create_all().
set -e

case "$DATABASE_URL" in
    sqlite*)
        echo "[entrypoint] SQLite: bo qua Alembic, app tu tao bang."
        ;;
    *)
        echo "[entrypoint] alembic upgrade head ..."
        alembic upgrade head
        ;;
esac

exec "$@"
