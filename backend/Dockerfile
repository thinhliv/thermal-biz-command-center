FROM python:3.12-slim

# psycopg2-binary co san wheel manylinux cho cp312 nen khong can gcc/libpq-dev.
# Cai chung vao image runtime chi them ~250MB va them be mat tan cong.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Alembic phai co trong image: entrypoint chay `alembic upgrade head` truoc uvicorn.
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY app/ ./app/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Khong chay uvicorn bang root: mot loi RCE trong app khong duoc quyen ghi he thong.
RUN useradd --create-home --uid 10001 appuser \
    && chmod 0755 /usr/local/bin/docker-entrypoint.sh
USER appuser

EXPOSE 8080

# /api/health tra 200 ca khi DB chet (body status=degraded) -> phai doc body,
# neu khong healthcheck bao "healthy" cho mot API khong dung duoc.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import json,sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4); sys.exit(0 if json.load(r).get('status')=='ok' else 1)"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
