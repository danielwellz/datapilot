SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

BACKEND := backend
# Flask's default port 5000 is taken by AirPlay Receiver on macOS.
FLASK_PORT := 5001

# Defaults for `make seed`; override on the command line: make seed scale=full
scale ?= small
seed ?= 42
# Measured runs per scenario for `make explain`.
runs ?= 10

.PHONY: help up down logs reset-db \
	be-install be-dev be-test be-lint be-format be-typecheck \
	db-migrate db-upgrade seed explain \
	fe-install fe-dev fe-test fe-lint fe-build \
	hooks check demo

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

seed: ## Load sales data: make seed scale=small|full [seed=42]
	cd $(BACKEND) && uv run flask --app app seed --scale $(scale) --seed $(seed)

explain: ## EXPLAIN ANALYZE the orders queries on the dev database: make explain [runs=10]
	cd $(BACKEND) && uv run python -m scripts.explain_orders --runs $(runs)

# --- Frontend -------------------------------------------------------------

FRONTEND_PENDING = @echo "$@ is available from Stage 7 (Angular web foundation)."

fe-install: ## Install frontend dependencies
	$(FRONTEND_PENDING)

fe-dev: ## Run the Angular development server
	$(FRONTEND_PENDING)

fe-test: ## Run frontend unit tests
	$(FRONTEND_PENDING)

fe-lint: ## Lint the frontend
	$(FRONTEND_PENDING)

fe-build: ## Build the frontend for production
	$(FRONTEND_PENDING)

# --- Workflow -------------------------------------------------------------

hooks: ## Install the git pre-commit hook
	cd $(BACKEND) && uv run pre-commit install --hook-type pre-commit

check: be-lint be-typecheck be-test ## Run every lint, type check and test suite

demo: ## Run the full production-like stack
	@echo "demo is available from Stage 11 (production readiness)."
