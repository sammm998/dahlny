# VS-Kalkyl – vanliga kommandon (SPEC 12). Backend-venv i backend/.venv.
SHELL := /bin/bash
VENV ?= backend/.venv
PY := $(abspath $(VENV))/bin/python
BIN := $(abspath $(VENV))/bin
PYTHON ?= python3.12
TEST_DATABASE_URL ?= postgresql+psycopg://vskalkyl:vskalkyl@localhost:5432/vskalkyl_test
export TEST_DATABASE_URL

.PHONY: help setup db-up db-down migrate dev test lint fmt typecheck check eval ai-smoke clean

help:
	@echo "make setup      – skapa backend/.venv och installera beroenden (Python 3.12)"
	@echo "make db-up      – starta PostgreSQL+PostGIS och Redis i Docker"
	@echo "make migrate    – kör Alembic-migreringar mot DATABASE_URL"
	@echo "make dev        – starta API:t lokalt (http://localhost:8000, /health)"
	@echo "make test       – pytest (kräver databas, se db-up)"
	@echo "make lint       – ruff check + format --check"
	@echo "make typecheck  – mypy --strict"
	@echo "make check      – lint + typecheck + test (samma som CI)"
	@echo "make eval       – utvärdering mot facitprojekten → eval/reports/eval.md"
	@echo "make ai-smoke   – ett riktigt AI-anrop (T0) som loggas i ai_run"

setup:
	@if command -v uv >/dev/null; then \
		uv venv -q -p 3.12 $(VENV) && uv pip install -q -p $(PY) -e 'backend[dev]'; \
	else \
		$(PYTHON) -m venv $(VENV) && $(PY) -m pip install -q -e 'backend[dev]'; \
	fi

db-up:
	docker compose up -d db redis

db-down:
	docker compose down

migrate:
	cd backend && $(BIN)/alembic upgrade head

dev: migrate
	cd backend && $(BIN)/uvicorn app.main:app --reload --port 8000

test:
	cd backend && $(PY) -m pytest

lint:
	cd backend && $(BIN)/ruff check . ../eval && $(BIN)/ruff format --check . ../eval

fmt:
	cd backend && $(BIN)/ruff format . ../eval && $(BIN)/ruff check --fix . ../eval

typecheck:
	cd backend && $(BIN)/mypy app tests ../eval/run_eval.py

check: lint typecheck test

eval:
	$(PY) eval/run_eval.py $(ARGS)

ai-smoke: migrate
	cd backend && $(PY) -m app.ai.smoke

clean:
	rm -rf backend/.mypy_cache backend/.ruff_cache backend/.pytest_cache eval/reports
