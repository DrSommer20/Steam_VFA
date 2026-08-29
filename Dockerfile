# syntax=docker/dockerfile:1
#
# Ein Image, drei Rollen: Webserver, Sammler und Discord-Bot starten daraus
# mit unterschiedlichem Command (siehe docker-compose.yml).

# ---------------------------------------------------------------- build-stage
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt

# ----------------------------------------------------------------- run-stage
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    TZ=Europe/Berlin \
    DB_PATH=/data/steamhub.db \
    PLAYERS_FILE=/data/players.json \
    HOST=0.0.0.0 \
    PORT=8077

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY app/ ./app/
COPY bot/ ./bot/
COPY frontend/ ./frontend/
COPY data/coop_seed.json ./data/coop_seed.json

# Nicht als root laufen. /data gehoert dem App-User - ein *named volume*
# uebernimmt diese Rechte beim ersten Mount automatisch.
RUN useradd --system --uid 10001 --home /app steamhub \
 && mkdir -p /data \
 && chown -R steamhub:steamhub /app /data
USER steamhub

VOLUME ["/data"]
EXPOSE 8077

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8077/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8077"]
