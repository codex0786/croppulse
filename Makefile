# CropPulse developer commands. Run from the repository root.
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
BACKEND = backend
export PYTHONPATH := $(CURDIR)/$(BACKEND)

.PHONY: setup dev api web test test-live lint typecheck migrate seed ingest assess deliver research-fetch evaluate report docker-up docker-down backup check

setup:            ## create venv, install backend + web dependencies
	python3.12 -m venv .venv
	$(PIP) install -e "$(BACKEND)[dev]"
	cd web && npm ci

migrate:          ## apply database migrations
	cd $(BACKEND) && ../$(PY) -m alembic upgrade head

seed:             ## create local development accounts (+ labelled synthetic demo field)
	$(PY) scripts/seed_dev.py --synthetic-demo

api:              ## run the API on :8000
	cd $(BACKEND) && ../$(PY) -m uvicorn croppulse.api.main:app --host 127.0.0.1 --port 8000 --reload

web:              ## run the web app on :3000
	cd web && npm run dev

dev:              ## API + web together (Ctrl-C stops both)
	$(MAKE) -j2 api web

test:             ## backend tests (offline, synthetic fixtures) + web i18n tests
	cd $(BACKEND) && ../$(PY) -m pytest
	cd web && npm test

test-live:        ## tests that call the real NASA/ORNL services
	cd $(BACKEND) && ../$(PY) -m pytest -m live

lint:
	.venv/bin/ruff check $(BACKEND)/croppulse $(BACKEND)/tests scripts
	cd web && npx next lint

typecheck:
	.venv/bin/mypy $(BACKEND)/croppulse
	cd web && npx tsc --noEmit

ingest:           ## refresh data + assessments for every registered field (live sources)
	$(PY) scripts/run_ingestion.py

assess:           ## re-run assessments on stored data, no downloads
	$(PY) scripts/run_ingestion.py --assess-only

deliver:          ## deliver pending notifications through the configured provider
	$(PY) scripts/run_ingestion.py --deliver-only

research-fetch:   ## download real MODIS/POWER data for research sample points (slow: ~45 min/point)
	$(PY) scripts/research_fetch.py

evaluate:         ## coverage report + descriptive backtest (real data) + synthetic mechanics check
	$(PY) scripts/run_evaluation.py

report: evaluate  ## alias: regenerate reports/

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

backup:           ## SQLite: consistent copy; PostgreSQL: see docs/OPERATIONS.md
	$(PY) scripts/backup_sqlite.py

check: lint typecheck test
