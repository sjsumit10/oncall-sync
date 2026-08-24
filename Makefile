.DEFAULT_GOAL := help
COMPOSE := docker compose

help: ## List targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

up: ## Start postgres, redis, api and worker
	$(COMPOSE) up -d --build

down: ## Stop everything
	$(COMPOSE) down

logs: ## Tail api + worker
	$(COMPOSE) logs -f api worker

db-bootstrap: ## Create the least-privileged app role (run once, before migrate)
	$(COMPOSE) run --rm api python scripts/bootstrap_db.py

migrate: db-bootstrap ## Bootstrap the app role and apply migrations
	$(COMPOSE) run --rm api alembic upgrade head

revision: ## Autogenerate a migration: make revision m="add sync_rules"
	$(COMPOSE) run --rm api alembic revision --autogenerate -m "$(m)"

test: ## Backend tests
	cd backend && pytest

lint: ## Ruff + mypy
	cd backend && ruff check . && ruff format --check . && mypy app

web: ## Frontend dev server
	cd frontend && npm run dev

.PHONY: help up down logs db-bootstrap migrate revision test lint web
