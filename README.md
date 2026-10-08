# DataPilot

Analytics and plain-English querying over a multi-million-row sales dataset, built with Flask, PostgreSQL, Redis and Angular.

This project is under active development. Full documentation will follow.

## Local development

Prerequisites: Docker with Compose, [uv](https://docs.astral.sh/uv/), GNU Make.

```bash
cp .env.example .env
make up          # PostgreSQL on localhost:5433, Redis on localhost:6379
make be-install  # backend dependencies
make check       # lint, type checks and tests
make be-dev      # API on http://localhost:5001
```

With the API running, the interactive documentation is at <http://localhost:5001/api/docs> and the OpenAPI document at <http://localhost:5001/api/openapi.json>.

Run `make help` to list every target.

### Sample data

The seed command generates a realistic, deterministic sales history: three years of orders with yearly growth, holiday peaks, weekday patterns, repeat customers, refunds and cancellations.

```bash
make db-upgrade
make seed               # small: 2,000 customers, 100 products, 50,000 orders
make seed scale=full    # full: 50,000 customers, 1,000 products, 2,000,000 orders
```

The same `seed` value (default 42) and end date always produce the same rows: `cd backend && uv run flask --app app seed --scale full --seed 42 --end-date 2026-10-08`. Without `--end-date`, the history ends today (UTC). The full scale takes about 1.5 minutes on an Apple M4 laptop. The design is in [ADR 0004](docs/adr/0004-deterministic-seed-data.md).

Seeding also creates a demo account: `demo@datapilot.dev` with the password `DataPilot-demo-2026`.

## License

[MIT](LICENSE)
