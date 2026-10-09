# DataPilot

Analytics and plain-English querying over a multi-million-row sales dataset, built with Flask, PostgreSQL, Redis and Angular.

This project is under active development. Full documentation will follow.

## Local development

Prerequisites: Docker with Compose, [uv](https://docs.astral.sh/uv/), Node.js 24 LTS (the version is pinned in `frontend/.node-version`), GNU Make.

```bash
cp .env.example .env
make up          # PostgreSQL on localhost:5433, Redis on localhost:6379
make be-install  # backend dependencies
make fe-install  # frontend dependencies
make check       # lint, type checks and tests for both
make be-dev      # API on http://localhost:5001
make fe-dev      # web app on http://localhost:4200 (in a second terminal)
```

With the API running, the interactive documentation is at <http://localhost:5001/api/docs> and the OpenAPI document at <http://localhost:5001/api/openapi.json>.

Run `make help` to list every target.

### Web app

The Angular app runs at <http://localhost:4200>. Its dev server forwards `/api` to the API on port 5001, so the browser sees one origin, as it will in production. Log in with the demo account below or create an account.

- **Design:** [docs/design.md](docs/design.md) holds the brief, the color, type, spacing and radius tokens with their contrast ratios, and the shell layout. Every token is a CSS custom property in `frontend/src/styles/_tokens.scss`, with light and dark values. The app follows the system theme until you pick one.
- **Dashboard:** key numbers for 7, 30 or 90 days with their change against the previous period, monthly revenue with a 3-month average, the top customers by country, the top products by category, and retention by signup month as a heatmap. All panels load in parallel; the charts below the fold render when they scroll into view. Every chart can also be read as a table.
- **Ask your data:** type a question, pick a model and get a query receipt: the explanation, the model that answered, the rows, the time, any assumptions, the SQL that ran (highlighted, copyable) and the result, with a chart when the result's shape fits the model's suggestion. A refused, failed or rate-limited question keeps its receipt with what happened and what to try next. Your earlier questions are listed beside the thread; choosing one shows its stored receipt and runs it again only when you ask.
- **Sessions:** the access token lives only in memory. The refresh token is an httpOnly cookie that the app never reads ([ADR 0003](docs/adr/0003-authentication-tokens.md)). A reload restores the session with one refresh call before the first page renders. When a request gets a 401, the app refreshes once, however many requests failed at the same moment, retries them, and sends you to log in only if the server rejects the refresh token.
- **Checks:** `make fe-lint` (ESLint and Prettier), `make fe-test` (Vitest, with coverage) and `make fe-build`.

### Sample data

The seed command generates a realistic, deterministic sales history: three years of orders with yearly growth, holiday peaks, weekday patterns, repeat customers, refunds and cancellations.

```bash
make db-upgrade
make seed               # small: 2,000 customers, 100 products, 50,000 orders
make seed scale=full    # full: 50,000 customers, 1,000 products, 2,000,000 orders
```

The same `seed` value (default 42) and end date always produce the same rows: `cd backend && uv run flask --app app seed --scale full --seed 42 --end-date 2026-10-08`. Without `--end-date`, the history ends today (UTC). The full scale takes about 1.5 minutes on an Apple M4 laptop. The design is in [ADR 0004](docs/adr/0004-deterministic-seed-data.md).

Seeding also creates a demo account: `demo@datapilot.dev` with the password `DataPilot-demo-2026`.

### Performance

On the full dataset, every measured orders list and detail request has a p95 under 15 ms, at any page depth. [docs/performance.md](docs/performance.md) has the measurements before and after indexing, the query plans, and the reasoning behind each index. `make explain` runs the EXPLAIN scenarios again on your database. Pagination uses signed keyset cursors ([ADR 0005](docs/adr/0005-keyset-pagination.md)).

The analytics endpoints (`/api/analytics/summary`, `revenue-monthly`, `top-customers`, `products`, `cohorts`) answer from a Redis cache in under 10 ms at p95, and in under 425 ms uncached. `make explain-analytics` shows their plans. The SQL and the cache design are in [ADR 0006](docs/adr/0006-analytics-sql-and-caching.md).

### Ask your data

`POST /api/ai/ask` answers a question in plain English with a read-only SQL query written by a language model, and returns the SQL, a short explanation, the rows and a suggested chart. The model is chosen per question from a registry (`backend/app/ai/llm_models.toml`): Groq, Google Gemini and OpenRouter through their OpenAI-compatible APIs, and Anthropic. A provider is offered once its API key is set in `.env`. Without any key, a deterministic demo model answers the example questions (`GET /api/ai/examples`), so the feature works offline.

```bash
make db-upgrade
make db-roles    # gives the read-only role its password from READONLY_DATABASE_URL
```

Model output is treated as untrusted input, whichever model wrote it. The SQL only ever reads four curated views without personal data. It must pass a parser-based guard, runs as a read-only database role in a read-only transaction with a statement timeout and a row limit, and gets at most one repair attempt; every question is audited. [ADR 0007](docs/adr/0007-text-to-sql-safety.md) describes each layer. `make eval-ask` runs 15 golden questions against the enabled models and writes the comparison to [docs/ai-evaluation.md](docs/ai-evaluation.md): on 2026-10-08, GPT-OSS 120B and Gemini 3.5 Flash-Lite answered all 15 correctly and Qwen3.8 27B 12.

## License

[MIT](LICENSE)
