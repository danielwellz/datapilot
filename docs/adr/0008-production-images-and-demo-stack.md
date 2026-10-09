# 8. Production images and the demo stack

- Status: Accepted
- Date: 2026-10-09

## Context

A reviewer must be able to run the whole application on a clean machine with one command, `cp .env.example .env && make demo`, and get a working app at <http://localhost:8080> with the demo account and no API keys. The same images should be close to what a real deployment runs: small, unprivileged, configured from the environment, with health checks and logs a machine can read.

The decisions below cover how the images are built, how the browser reaches the API, how the database is accessed, where the demo's secrets come from, and how the stack is tested.

## Decision

### Two images, built in stages

- **Backend** (`backend/Dockerfile`): a `dependencies` stage installs exactly the locked runtime dependencies with uv into a virtualenv. The `runtime` stage, `python:3.12-slim`, copies that virtualenv and the application, and nothing else: no uv, no compilers, no tests. The code is owned by root and read-only to the process, which runs as an unprivileged user (uid 10001). The health check calls `/api/health` with Python's own `urllib`, so the image needs no curl. 74 MB compressed.
- **Web** (`frontend/Dockerfile`): Node builds the Angular app; `nginxinc/nginx-unprivileged` serves it as the nginx user on port 8080. 25 MB compressed. npm install scripts stay off: no dependency needs one, because esbuild and lmdb ship prebuilt binaries.

Base images are pinned to a patch version and updated by Dependabot.

### Gunicorn with threads

Gunicorn runs `gthread` workers, two workers of four threads by default (`GUNICORN_WORKERS`, `GUNICORN_THREADS`). Requests spend most of their time waiting on PostgreSQL, Redis or a model provider, so threads serve them well. Each worker keeps its own connection pools; `preload_app` stays off so no pool is shared across a fork. Workers restart after about 2,000 requests, which bounds slow memory growth. Gunicorn's records go through the application's JSON log handler, and its access log is dropped because the application logs each request with its request id.

### One origin, behind Nginx

Nginx serves the Angular files and proxies `/api` to Gunicorn. The browser sees one origin, so there is no CORS, and the refresh cookie stays first-party with `SameSite=Strict`.

- **Caching:** files with a content hash in their name are cached for a year (`immutable`). `index.html` and the few unhashed files (`theme.js`, `favicon.svg`) are revalidated on every load, so a deploy is picked up at once. Other paths fall back to `index.html` for client-side routes, but a missing hashed file is a 404, never HTML served as a script.
- **Headers:** every page carries a Content-Security-Policy that allows scripts from the origin only, plus `nosniff`, a referrer policy, a permissions policy and `Cross-Origin-Opener-Policy`. They come from one snippet included in each location, because `add_header` in a location replaces the headers set around it. The saved-theme script moved out of `index.html` into `public/theme.js` so the policy needs no hash, and Angular's critical-CSS inlining is off because it adds an inline script. Inline styles are allowed: Angular inserts component styles at runtime.
- **API headers** are set by Flask, not Nginx: every JSON response forbids rendering, framing and sniffing, and the Swagger UI page gets its own policy that allows its pinned CDN path and its one inline script by hash.
- **Client addresses:** Nginx appends the client's address to `X-Forwarded-For`, and the API trusts exactly one hop (`TRUSTED_PROXY_HOPS=1`, applied with Werkzeug's `ProxyFix`). Each client then has its own login rate limit, and an address a client writes into the header itself is ignored.

### The API does not own the database

The demo's PostgreSQL has three roles:

| Role | Used by | Can |
| --- | --- | --- |
| `datapilot` (owner) | the one-shot `migrate` job: migrations, `db-roles`, the seed | everything |
| `datapilot_app` | the API | read and write rows; not create, alter or drop objects, change roles or read server files |
| `datapilot_readonly` | Ask your data | read four curated views ([ADR 0007](0007-text-to-sql-safety.md)) |

The first plan was a non-superuser owner with `CREATEROLE` for both the migrations and the API. It does not work on PostgreSQL 16: a committed migration sets `NOSUPERUSER NOREPLICATION NOBYPASSRLS` on the read-only role, and only a superuser may name those attributes, even unchanged. Committed migrations are never edited. So the owner keeps running migrations, and the API connects as a role that owns nothing, which is stricter than the plan: a compromised API process cannot change the schema. `infra/postgres/demo/01-create-app-role.sh` creates the role when the volume is first initialized, with default privileges so every table the migrations create later is covered.

Development and CI keep one superuser role, as before.

### The demo stack is its own Compose project

`docker-compose.demo.yml` runs as the project `datapilot-demo`, with its own volumes and no database or Redis port on the host, so it never touches the development services. Only Nginx is published, on the loopback address, because the demo account's password is public.

- **Start-up:** PostgreSQL and Redis become healthy; the `migrate` job runs migrations, sets the read-only role's password and loads the small dataset with the demo account if there are no orders (`flask seed --if-empty`); the API starts when that job has succeeded, and Nginx when the API is healthy. `make demo` waits until all of them are.
- **Production settings:** `APP_ENV=production`, so the weak-secret checks apply, cookies are `Secure` and seeding over existing data needs `--yes`. Application containers have a read-only root file system, no Linux capabilities and `no-new-privileges`.
- **Secrets:** `make demo` writes random values once to `.env.demo` (untracked, mode 600). Fixed demo secrets in the repository would give everyone the same JWT key and defeat the production checks. API keys and model settings come from `.env`; without any key, Ask your data uses the demo model.
- **Redis** is bounded at 256 MB with `volatile-lru`. Every cache entry, token and rate-limit counter has a TTL; the data version key has none and is never evicted.

### Testing the stack

A Playwright smoke test (`e2e/`) logs in with the demo account, reloads, opens an order and asks an example question with the demo model. It runs against the running stack, so it tests the production images and configuration. CI builds and starts the stack exactly as a reviewer would (`cp .env.example .env && make demo`) and runs the test; on a failure it prints the stack's logs and keeps the report.

## Consequences

- A reviewer needs only Docker, Make and OpenSSL. From a fresh clone, `make demo` took 36 seconds with the base images already pulled; a first run also downloads them.
- The images are deployable as they are, given real secrets and a TLS-terminating proxy or load balancer in front of Nginx. HSTS is not set, because the demo is served over plain HTTP on localhost.
- The read-only database role's password is set by the `migrate` job on every start, so changing it in `.env.demo` only needs a restart. The owner and app passwords are fixed when the volume is created: `make demo-reset` deletes the volumes to start over.
- `datapilot_app` may write to every table, which is more than the API needs for sales data. Narrower grants per table are possible later.
