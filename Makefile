SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend
E2E := e2e
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
# `make demo scale=full`: the full dataset's order count (SCALES in
# app/seed/generator.py), and the free space Docker's disk must have before
# loading it: about 2 GB of tables and indexes, plus the write-ahead log the
# load produces before checkpoints recycle it, with room to spare.
FULL_SCALE_ORDERS := 2000000
DEMO_FULL_MIN_FREE_GB := 6

.PHONY: help up down logs reset-db \
	be-install be-dev be-stop be-test be-lint be-format be-typecheck \
	db-migrate db-upgrade db-roles seed explain explain-analytics bench eval-ask \
	fe-install fe-dev fe-test fe-lint fe-format fe-build \
	e2e-install e2e e2e-typecheck \
	hooks check demo demo-full-data demo-down demo-reset demo-logs

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

# --- Infrastructure -------------------------------------------------------

up: ## Start PostgreSQL and Redis and wait until they are healthy
	docker compose up -d --wait

down: be-stop ## Stop PostgreSQL and Redis (data volumes are kept)
	docker compose down

logs: ## Follow PostgreSQL and Redis logs
	docker compose logs -f

reset-db: ## Delete the data volumes and start fresh (reruns init scripts)
	docker compose down -v
	docker compose up -d --wait

# --- Backend --------------------------------------------------------------

be-install: ## Install backend dependencies exactly as locked
	cd $(BACKEND) && uv sync --locked

be-dev: be-stop ## Run the Flask development server on port 5001
	cd $(BACKEND) && uv run flask --app app run --debug --port $(FLASK_PORT)

# When the debug server is stopped from a parent process, its reloader child
# can survive and keep port 5001, so the next server cannot bind or requests
# hang. Only a process running this project's `flask ... run` is stopped;
# anything else on the port is reported and left alone.
be-stop: ## Stop a development server still listening on port 5001
	@for pid in $$(lsof -t -iTCP:$(FLASK_PORT) -sTCP:LISTEN 2>/dev/null); do \
		if ps -o command= -p "$$pid" | grep -q 'flask --app app run'; then \
			kill "$$pid"; \
			for _ in 1 2 3 4 5 6 7 8 9 10; do \
				kill -0 "$$pid" 2>/dev/null || break; sleep 0.5; \
			done; \
			echo "Stopped the development server left on port $(FLASK_PORT) (pid $$pid)."; \
		else \
			echo "Port $(FLASK_PORT) is used by another program (pid $$pid); stop it first." >&2; \
			exit 1; \
		fi; \
	done

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

bench: ## Measure the API latencies in the README; the API must be running [args="--skip-uncached"]
	cd $(BACKEND) && uv run python -m scripts.bench_suite $(args)

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

# --- End-to-end -----------------------------------------------------------

e2e-install: ## Install the smoke test's dependencies and its Chromium
	cd $(E2E) && npm ci && npx playwright install chromium

e2e: ## Run the browser smoke test against the running demo stack (make demo)
	cd $(E2E) && npx playwright test

e2e-typecheck: ## Type-check the smoke test
	cd $(E2E) && npx tsc --noEmit

# --- Workflow -------------------------------------------------------------

hooks: ## Install the git pre-commit hook
	cd $(BACKEND) && uv run pre-commit install --hook-type pre-commit

check: be-lint be-typecheck be-test fe-lint fe-test fe-build e2e-typecheck ## Run every lint, type check and test suite (the pre-push command)

# --- Demo stack -----------------------------------------------------------

# Written once with random values and kept: the database volume remembers the
# passwords it was created with. Not tracked (.gitignore: .env.*).
.env.demo:
	@umask 077 && for name in $(DEMO_SECRETS); do \
		printf '%s=%s\n' "$$name" "$$(openssl rand -hex 32)"; \
	done > $@
	@echo "Wrote random demo secrets to $@."

demo: .env.demo ## Build and run the production-like stack at http://localhost:8080 [scale=full]
	@test -f .env || { echo "Create .env first: cp .env.example .env"; exit 1; }
	@case "$(scale)" in \
		small) ;; \
		full) $(MAKE) --no-print-directory demo-full-data ;; \
		*) echo "scale must be small or full, not $(scale)." >&2; exit 1 ;; \
	esac
	$(DEMO_COMPOSE) up --build --detach --wait
	@echo "DataPilot is running at http://localhost:8080"
	@echo "Log in as demo@datapilot.dev with the password DataPilot-demo-2026."

# Loads the full dataset before the API starts: the seed truncates the sales
# tables in one transaction, so a running API would wait on its locks and
# answer 503 for the whole load. Skipped when the data is already there; the
# migrate job's `seed --if-empty` then leaves it alone on every start.
demo-full-data: .env.demo
	$(DEMO_COMPOSE) build
	$(DEMO_COMPOSE) up --detach --wait postgres redis
	@orders=$$($(DEMO_COMPOSE) exec -T postgres \
		psql -U datapilot -d datapilot -tAc 'SELECT count(*) FROM orders' 2>/dev/null || echo 0); \
	if [ "$$orders" -ge $(FULL_SCALE_ORDERS) ]; then \
		echo "The demo stack already holds the full dataset ($$orders orders)."; \
		exit 0; \
	fi; \
	free_kb=$$($(DEMO_COMPOSE) exec -T postgres df -Pk /var/lib/postgresql/data | awk 'NR == 2 { print $$4 }'); \
	free_gb=$$((free_kb / 1024 / 1024)); \
	if [ "$$free_gb" -lt $(DEMO_FULL_MIN_FREE_GB) ]; then \
		echo "Docker's disk has $$free_gb GB free; the full dataset needs at least $(DEMO_FULL_MIN_FREE_GB) GB." >&2; \
		echo "Free space (for example docker builder prune) or run make demo for the small dataset." >&2; \
		exit 1; \
	fi; \
	echo "Loading the full dataset (2,000,000 orders) into the demo stack. It replaces the"; \
	echo "demo's sales data and takes about 2 minutes and 2 GB of Docker disk ($$free_gb GB free)."; \
	$(DEMO_COMPOSE) stop backend web; \
	$(DEMO_COMPOSE) run --rm migrate \
		sh -c "flask db upgrade && flask db-roles && flask seed --scale full --yes"

demo-down: ## Stop the demo stack (its data volumes are kept)
	$(DEMO_COMPOSE) down

demo-reset: ## Stop the demo stack and delete its data volumes
	$(DEMO_COMPOSE) down --volumes

demo-logs: ## Follow the demo stack's logs
	$(DEMO_COMPOSE) logs -f
