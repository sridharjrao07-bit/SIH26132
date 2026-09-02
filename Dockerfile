# SIH26132 — Krishi Bazaar API
# Single worker: in-process APScheduler + job locks assume --workers 1.
FROM python:3.14-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUN_SCHEDULER=1 \
    RATE_LIMIT_ENABLED=1 \
    APP_ENV=production

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY ingestion ./ingestion
COPY forecasting ./forecasting
COPY notifications ./notifications
COPY templates ./templates
COPY db ./db

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
