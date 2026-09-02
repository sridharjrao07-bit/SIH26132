.PHONY: install install-dev lint test run compose-up compose-down audit

PY ?= python
export RUN_SCHEDULER ?= 0
export RATE_LIMIT_ENABLED ?= 0

install:
	$(PY) -m pip install -r requirements.txt

install-dev:
	$(PY) -m pip install -r requirements-dev.txt

lint:
	ruff check app ingestion forecasting notifications tests demo scripts

test:
	pytest -q

audit:
	pip-audit -r requirements.txt

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

compose-up:
	docker compose up --build

compose-down:
	docker compose down
