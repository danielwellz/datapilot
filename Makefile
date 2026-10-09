SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend
# Flask's default port 5000 is taken by AirPlay Receiver on macOS.
FLASK_PORT := 5001

# Defaults for `make seed`; override on the command line: make seed scale=full
scale ?= small
seed ?= 42
# Measured runs per scenario for `make explain` and `make explain-analytics`.
runs ?= 10

# The production-like stack: its own Compose project, secrets from .env.demo.
DEMO_COMPOSE := docker compose -f docker-compose.demo.yml --env-file .env --env-file .env.demo
DEMO_SECRETS := DEMO_SECRET_KEY DEMO_JWT_SECRET_KEY DEMO_POSTGRES_PASSWORD \
	DEMO_APP_DB_PASSWORD DEMO_READONLY_DB_PASSWORD

.PHONY: help up down logs reset-db \
	be-install be-dev be-test be-lint be-format be-typecheck \
	db-migrate db-upgrade db-roles seed explain explain-analytics eval-ask \
	fe-install fe-dev fe-test fe-lint fe-format fe-build \
	hooks check demo demo-down demo-reset demo-logs

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

# --- Infrastructure -------------------------------------------------------

up: ## Start PostgreSQL and Redis and wait until they are healthy
	docker compose up -d --wait

down: ## Stop PostgreSQL and Redis (data volumes are kept)
	docker compose down

logs: ## Follow PostgreSQL and Redis logs
	docker compose logs -f

reset-db: ## Delete the data volumes and start fresh (reruns init scripts)
	docker compose down -v
	docker compose up -d --wait

# --- Backend --------------------------------------------------------------

be-install: ## Install backend dependencies exactly as locked
	cd $(BACKEND) && uv sync --locked

be-dev: ## Run the Flask development server on port 5001
	cd $(BACKEND) && uv run flask --app app run --debug --port $(FLASK_PORT)

be-test: ## Run backend tests with coverage
	cd $(BACKEND) && uv run pytest

be-lint: ## Lint and check formatting of the backend
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check .

be-format: ## Apply ruff fixes and formatting to the backend
	cd $(BACKEND) && uv run ruff check --fix . && uv run ruff format .

be-typecheck: ## Type-check the backend with mypy --strict
	cd $(BACKEND) && uv run mypy

# --- Database -------------------------------------------------------------

db-migrate: ## Autogenerate a migration: make db-migrate m="message"
	@test -n "$(m)" || { echo 'Usage: make db-migrate m="describe the change"'; exit 1; }
	cd $(BACKEND) && uv run flask --app app db migrate -m "$(m)"

db-upgrade: ## Apply migrations to the development database
	cd $(BACKEND) && uv run flask --app app db upgrade

db-roles: ## Set the read-only role's password from READONLY_DATABASE_URL (after db-upgrade)
	cd $(BACKEND) && uv run flask --app app db-roles

seed: ## Load sales data: make seed scale=small|full [seed=42]
	cd $(BACKEND) && uv run flask --app app seed --scale $(scale) --seed $(seed)

explain: ## EXPLAIN ANALYZE the orders queries on the dev database: make explain [runs=10]
	cd $(BACKEND) && uv run python -m scripts.explain_orders --runs $(runs)

explain-analytics: ## EXPLAIN ANALYZE the analytics queries: make explain-analytics [runs=10]
	cd $(BACKEND) && uv run python -m scripts.explain_analytics --runs $(runs)

eval-ask: ## Ask the golden questions of the enabled models; writes docs/ai-evaluation.md [args="--models a,b"]
	cd $(BACKEND) && uv run python -m scripts.eval_ask $(args)

# --- Frontend -------------------------------------------------------------

fe-install: ## Install frontend dependencies exactly as locked
	cd $(FRONTEND) && npm ci

fe-dev: ## Run the Angular dev server on port 4200 (proxies /api to port 5001)
	cd $(FRONTEND) && npx ng serve

fe-test: ## Run frontend unit tests once, with coverage
	cd $(FRONTEND) && npx ng test --watch=false --coverage

fe-lint: ## Lint the frontend and check its formatting
	cd $(FRONTEND) && npx ng lint && npx prettier --check .

fe-format: ## Apply Prettier formatting to the frontend
	cd $(FRONTEND) && npx prettier --write .

fe-build: ## Build the frontend for production (includes the template type check)
	cd $(FRONTEND) && npx ng build

# --- Workflow -------------------------------------------------------------

hooks: ## Install the git pre-commit hook
	cd $(BACKEND) && uv run pre-commit install --hook-type pre-commit

check: be-lint be-typecheck be-test fe-lint fe-test fe-build ## Run every lint, type check and test suite

# --- Demo stack -----------------------------------------------------------

# Written once with random values and kept: the database volume remembers the
# passwords it was created with. Not tracked (.gitignore: .env.*).
.env.demo:
	@umask 077 && for name in $(DEMO_SECRETS); do \
		printf '%s=%s\n' "$$name" "$$(openssl rand -hex 32)"; \
	done > $@
	@echo "Wrote random demo secrets to $@."

demo: .env.demo ## Build and run the production-like stack at http://localhost:8080
	@test -f .env || { echo "Create .env first: cp .env.example .env"; exit 1; }
	$(DEMO_COMPOSE) up --build --detach --wait
	@echo "DataPilot is running at http://localhost:8080"
	@echo "Log in as demo@datapilot.dev with the password DataPilot-demo-2026."

demo-down: ## Stop the demo stack (its data volumes are kept)
	$(DEMO_COMPOSE) down

demo-reset: ## Stop the demo stack and delete its data volumes
	$(DEMO_COMPOSE) down --volumes

demo-logs: ## Follow the demo stack's logs
	$(DEMO_COMPOSE) logs -f
