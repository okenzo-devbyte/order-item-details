FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    SNAPSHOT_PATH=/app/data/snapshot.enc

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY api/ api/
COPY web/ web/
COPY scripts/ scripts/
COPY snapshot.enc data/snapshot.enc

RUN python -c "import sqlite3; sqlite3.connect(':memory:').execute(\"CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')\")"

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 7860
CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips "*"
