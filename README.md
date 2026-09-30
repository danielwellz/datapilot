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

## License

[MIT](LICENSE)
