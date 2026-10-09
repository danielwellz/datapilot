# Development

How to run DataPilot from source, load data, and work on the backend and the web app. For the production-like stack, `make demo` in the [README](../README.md) is enough.

## Setup

Prerequisites: Docker with Compose, [uv](https://docs.astral.sh/uv/), Node.js 24 LTS (pinned in `frontend/.node-version`), GNU Make.

```bash
cp .env.example .env
make up          # PostgreSQL on localhost:5433, Redis on localhost:6379
make be-install  # backend dependencies, exactly as locked
make fe-install  # frontend dependencies, exactly as locked
make db-upgrade  # migrations
make db-roles    # gives the read-only role its password from READONLY_DATABASE_URL
make seed        # the small dataset and the demo account
make be-dev      # API on http://localhost:5001
make fe-dev      # web app on http://localhost:4200 (in a second terminal)
```

Flask runs on port 5001 because macOS uses 5000 for AirPlay Receiver, and PostgreSQL is published on 5433 to avoid a local installation. The Angular dev server forwards `/api` to the API, so the browser sees one origin, as it does in production. The interactive API documentation is at <http://localhost:5001/api/docs>, and the OpenAPI document at <http://localhost:5001/api/openapi.json>.

`make help` lists every target. If port 5001 is still held by a development server that did not stop cleanly, `make be-stop` (also run by `make be-dev` and `make down`) stops it; it refuses to touch any other program on that port.

## Sample data

The seed command generates a deterministic sales history: three years of orders with yearly growth, holiday peaks, weekday patterns, repeat customers, refunds and cancellations ([ADR 0004](adr/0004-deterministic-seed-data.md)).

```bash
make seed               # small: 2,000 customers, 100 products, 50,000 orders (about 3 s)
make seed scale=full    # full: 50,000 customers, 1,000 products, 2,000,000 orders (about 100 s)
```

- The same `seed` value (default 42) and end date always produce the same rows: `cd backend && uv run flask --app app seed --scale full --seed 42 --end-date 2026-10-08`. Without `--end-date`, the history ends today (UTC).
- Seeding replaces all sales data and bumps the cache's data version. `--if-empty` loads only into a database without orders; with `APP_ENV=production`, replacing existing data needs `--yes`.
- Seeding also creates the demo account, `demo@datapilot.dev` with the password `DataPilot-demo-2026`, if it does not exist.

## Configuration

Every setting is an environment variable, listed with its default in `.env.example` and validated at start-up by `backend/app/config.py`. A few worth knowing:

- `API_STATEMENT_TIMEOUT_MS` (3000): every statement an API request runs is cancelled after this long, and the API answers `503 statement_timeout`. CLI commands such as the seed are not limited.
- `TRUSTED_PROXY_HOPS` (0): how many proxies in front of the API to trust for the client address. The demo stack sets 1 for Nginx.
- `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`: each enables its provider's models in Ask your data. Without any key, the demo model answers the example questions.
- `LLM_DEFAULT_MODEL` and `LLM_FALLBACK_MODELS`: the default model and an explicit fallback order. Left empty, the fallbacks alternate providers ([ADR 0007](adr/0007-text-to-sql-safety.md)).

When PostgreSQL or Redis is unreachable, the API answers `503 service_unavailable` and logs which one failed.

## Backend

```bash
make be-test        # pytest against the test database and Redis, with coverage
make be-lint        # ruff check and format check
make be-typecheck   # mypy --strict
make be-format      # apply ruff fixes and formatting
make db-migrate m="add something"   # autogenerate a migration, then review it by hand
```

Tests need `make up`: they run against a real PostgreSQL test database and a separate Redis database index ([testing.md](testing.md)).

Measurement and evaluation scripts live in `backend/scripts/`:

- `make explain` and `make explain-analytics`: `EXPLAIN (ANALYZE, BUFFERS)` of the orders and analytics queries on the development database.
- `make bench`: the API latencies the README reports, against a running API ([performance.md](performance.md)).
- `make eval-ask`: the 15 golden questions against every enabled model, written to [ai-evaluation.md](ai-evaluation.md). It calls the providers, so it uses their quotas.

## Web app

```bash
make fe-test    # Vitest, with coverage
make fe-lint    # ESLint and Prettier
make fe-build   # production build, including the template type check
make fe-format  # apply Prettier
```

- **Design:** [design.md](design.md) holds the brief, the color, type, spacing and radius tokens with their contrast ratios, and the layout. Every token is a CSS custom property in `frontend/src/styles/_tokens.scss`, with light and dark values. The app follows the system theme until you pick one.
- **Sessions:** the access token lives only in memory; the refresh token is an httpOnly cookie the app never reads ([ADR 0003](adr/0003-authentication-tokens.md)). A reload restores the session with one refresh call before the first page renders. On a 401, the app refreshes once, however many requests failed at the same moment, retries them, and sends you to log in only if the server rejects the refresh token.
- **Dashboard:** all panels load in parallel; the charts below the fold render when they scroll into view, and every chart can also be read as a table.
- **Ask your data:** a refused, failed or rate-limited question keeps its receipt with what happened and what to try next. Earlier questions are listed beside the thread; choosing one shows its stored receipt and runs it again only when asked.

## End-to-end test and screenshots

Both run against the demo stack (`make demo`):

```bash
make e2e-install   # once: dependencies and Chromium
make e2e           # the smoke test
make screenshots   # docs/images in both themes; model="GPT-OSS 120B (Groq)" picks a real model
```

The committed screenshots were taken from `make demo scale=full`.

## Before pushing

```bash
make check
```

It runs every lint, type check and test suite for the backend and the frontend, and type-checks the end-to-end tests. CI runs the same checks, then builds the demo stack from a clean checkout and runs the smoke test against it. `make hooks` installs a pre-commit hook for whitespace, file endings and ruff.
