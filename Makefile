.DEFAULT_GOAL := help
COMPOSE := docker compose

# Prefer the local virtualenv when there is one, so `make test` works without
# having to remember to activate it.
BIN := $(shell [ -x backend/.venv/bin/pytest ] && echo .venv/bin/ || echo "")

help: ## List targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

up: ## Start postgres, redis, api and worker in docker
	$(COMPOSE) up -d --build

db-up: ## Start only postgres and redis (for running the app natively)
	$(COMPOSE) up -d postgres redis

install: ## Create backend/.venv and install backend + frontend dependencies
	cd backend && python3 -m venv .venv && .venv/bin/pip install -qe '.[dev]'
	cd frontend && npm install

down: ## Stop everything
	$(COMPOSE) down

logs: ## Tail api + worker
	$(COMPOSE) logs -f api worker

db-bootstrap: ## Create the least-privileged app role (run once, before migrate)
	$(COMPOSE) run --rm api python scripts/bootstrap_db.py

migrate: db-bootstrap ## Bootstrap the app role and apply migrations
	$(COMPOSE) run --rm api alembic upgrade head

migrate-native: ## Bootstrap and migrate from the host venv (native workflow)
	cd backend && $(BIN)python scripts/bootstrap_db.py && $(BIN)alembic upgrade head

api: ## Run the API natively with reload
	cd backend && $(BIN)uvicorn app.main:app --reload --port 8000

worker: ## Run the ARQ worker natively
	cd backend && $(BIN)arq app.worker.arq_app.WorkerSettings --watch app

revision: ## Autogenerate a migration: make revision m="add sync_rules"
	$(COMPOSE) run --rm api alembic revision --autogenerate -m "$(m)"

test-db: ## Create the test database (only if your pg volume predates it)
	@$(COMPOSE) exec -T postgres psql -U oncall -d postgres -tAc \
		"SELECT 1 FROM pg_database WHERE datname = 'oncall_test'" | grep -q 1 \
		|| $(COMPOSE) exec -T postgres createdb -U oncall oncall_test
	@echo "oncall_test ready"

test: ## Backend tests
	cd backend && $(BIN)pytest

test-all: ## Backend tests including the scale checks
	cd backend && $(BIN)pytest -m ''

audit: ## Architecture, security and scale guards
	cd backend && $(BIN)pytest tests/test_architecture.py tests/test_security.py \
		tests/test_extensibility.py tests/test_load.py -m ''

lint: ## Ruff + mypy
	cd backend && $(BIN)ruff check . && $(BIN)ruff format --check . && $(BIN)mypy app scripts

web: ## Frontend dev server
	cd frontend && npm run dev

.PHONY: help up db-up install down logs db-bootstrap migrate migrate-native \
	revision api worker test-db test test-all audit lint web
