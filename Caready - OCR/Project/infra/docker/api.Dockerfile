# Build context is the repo root so `config/` and `seed/` can be copied
# alongside the service.
FROM python:3.11-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq for psycopg, and the image libraries Pillow needs for the capture
# quality gate and the seed generators.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libjpeg62-turbo \
        libopenjp2-7 \
        libtiff6 \
        libfreetype6 \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a source edit does not invalidate the install layer.
COPY services/api/pyproject.toml /app/services/api/pyproject.toml
RUN pip install --upgrade pip setuptools wheel \
    && pip install -e "/app/services/api[dev]"

COPY services/api /app/services/api
COPY config /app/config
COPY seed /app/seed
COPY docs /app/docs

# Non-root. The bind mounts in docker-compose are read-write for dev reload,
# so the uid must own the source tree.
RUN useradd --create-home --uid 10001 caready \
    && chown -R caready:caready /app
USER caready

ENV PYTHONPATH=/app/services/api
WORKDIR /app/services/api

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
