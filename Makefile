SHELL := /bin/bash
.SHELLFLAGS := -eo pipefail -c

.PHONY: install install-dev lint test run compose-up compose-down audit db-apply db-apply-dry ci-local docs

PY ?= python
export RUN_SCHEDULER ?= 0
export RATE_LIMIT_ENABLED ?= 0

install:
	$(PY) -m pip install -r requirements.txt

install-dev:
	$(PY) -m pip install -r requirements-dev.txt

lint:
	$(PY) -m ruff check .

test:
	RUN_SCHEDULER=0 RATE_LIMIT_ENABLED=0 pytest

audit:
	pip-audit -r requirements.txt

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

compose-up:
	docker compose up --build

compose-down:
	docker compose down

db-apply:
	$(PY) scripts/apply_migrations.py

db-apply-dry:
	$(PY) scripts/apply_migrations.py --dry-run

ci-local:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	PYTHONPATH=. $(PY) scripts/generate_api_docs.py --check
	RUN_SCHEDULER=0 RATE_LIMIT_ENABLED=0 pytest -rs | tee test.log
	@unexpected="$$(grep -E '^SKIPPED' test.log | sed 's/.*py:[0-9]*: //' | sort -u | grep -vFf ci/allowed-skips.txt || true)"; \
	if [ -n "$$unexpected" ]; then \
		echo "❌ unaccepted skip reasons:"; echo "$$unexpected"; exit 1; \
	fi
	@rm -f test.log
	@echo "✅ clean — safe to push"

docs:
	PYTHONPATH=. $(PY) scripts/generate_api_docs.py
