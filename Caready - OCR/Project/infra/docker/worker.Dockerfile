# RQ workers: ICR extraction, vision inference, grading, and pricing.
#
# Separate image from the API because the worker carries the ML stack
# (LightGBM, scikit-learn, MLflow) which the API does not need. Keeping them
# apart avoids shipping ~400MB of numerical libraries into every API replica.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # LightGBM and numpy each spawn a thread pool sized to the host CPU count.
    # Inside a container that count is the host's, not the container's limit,
    # which produces heavy oversubscription. Pinned low; RQ gives concurrency.
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    MKL_NUM_THREADS=2

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libgomp1 \
        libjpeg62-turbo \
        libopenjp2-7 \
        libtiff6 \
        libfreetype6 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/api/pyproject.toml /app/services/api/pyproject.toml
COPY services/worker/pyproject.toml /app/services/worker/pyproject.toml
COPY packages/ml/pyproject.toml /app/packages/ml/pyproject.toml

RUN pip install --upgrade pip setuptools wheel \
    && pip install -e /app/services/api \
    && pip install -e /app/packages/ml \
    && pip install -e /app/services/worker

COPY services/api /app/services/api
COPY services/worker /app/services/worker
COPY packages/ml /app/packages/ml
COPY config /app/config

RUN useradd --create-home --uid 10001 caready \
    && chown -R caready:caready /app
USER caready

ENV PYTHONPATH=/app/services/api:/app/services/worker:/app/packages/ml

CMD ["python", "-m", "worker.main"]
