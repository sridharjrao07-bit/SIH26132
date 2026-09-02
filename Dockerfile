# SIH26132 — Krishi Bazaar API
# Single worker: in-process APScheduler + job locks assume --workers 1.
FROM python:3.14-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUN_SCHEDULER=1 \
    RATE_LIMIT_ENABLED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY ingestion ./ingestion
COPY forecasting ./forecasting
COPY notifications ./notifications
COPY templates ./templates
COPY db ./db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
