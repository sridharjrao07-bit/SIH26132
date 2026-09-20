# SIH26132 — Krishi Bazaar API
# Single worker: in-process APScheduler + job locks assume --workers 1.
#
# Two usage patterns:
#   api        RUN_SCHEDULER=0  — handles HTTP traffic only
#   api-worker RUN_SCHEDULER=1  — runs the scheduler (one replica only)
#
# See docker-compose.yml for the split-service definition.
FROM python:3.12-slim as base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RATE_LIMIT_ENABLED=1 \
    APP_ENV=production

# Install deps before copying source so this layer is cached between code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source.  Order matches .dockerignore exclusions.
COPY app ./app
COPY ingestion ./ingestion
COPY forecasting ./forecasting
COPY notifications ./notifications
COPY events ./events
COPY scripts ./scripts
COPY templates ./templates
COPY db ./db

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

# Readiness probe (/readyz) is preferred over liveness (/health) here because
# it confirms startup checks have passed before traffic is routed.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz')"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# --- Explicit ML Target ---
# Build this stage with `docker build --target ml .` to enable advanced ML models.
FROM base as ml

COPY requirements-forecast-ml.txt .
RUN pip install --no-cache-dir -r requirements-forecast-ml.txt

USER appuser

# Default target is base
FROM base as release
USER appuser
