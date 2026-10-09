# Testing

The tests are meant to prove behaviour against the real dependencies, not against stand-ins for them. The backend runs against PostgreSQL and Redis, the frontend tests its services, stores and components in isolation, and one browser test runs against the production images. `make check` runs everything a pull request needs, and CI runs the same checks plus the browser test.

| Suite | Runs | Size | Gate |
| --- | --- | --- | --- |
| Backend unit and integration (`backend/tests/`) | pytest against PostgreSQL 16 and Redis 7 | 1,072 tests, about 30 s | 85% line and branch coverage; currently 100% |
| Frontend unit (`frontend/src/**/*.spec.ts`) | Vitest through `ng test`, jsdom | 593 tests | 95% lines, statements and functions; 90% branches |
| End-to-end smoke (`e2e/tests/`) | Playwright, Chromium, against `make demo` | 1 test, under 2 s | Must pass in CI |
| Static checks | ruff, `mypy --strict`, ESLint, Prettier, `tsc` | whole codebase | No errors, no warnings |

## Backend

### Real PostgreSQL, one transaction per test

There is no SQLite and no mocked session. The integration harness (`backend/tests/integration/conftest.py`) does three things:

1. **Builds the schema from the migrations** once per session, so the migrations themselves are tested on every run. It refuses to start unless the database name ends in `_test`.
2. **Wraps each test in one outer transaction** that is rolled back afterwards. Sessions join it with `join_transaction_mode="create_savepoint"`, so code under test can `commit()` and `rollback()` as it does in production; those only move savepoints. Tests cannot see each other's data, and they can run in any order.
3. **Gives each test its own Redis database index**, flushed before and after.

`test_harness_isolation.py` proves the isolation itself: data committed by one test is gone in the next.

Test data comes from small factories (`backend/tests/factories.py`) that build exactly the rows a test needs, inside its transaction. The analytics tests use hand-built datasets whose expected numbers were worked out independently: ties in rankings, a month without sales, a refund kept out of revenue, orders one second either side of a period boundary.

### What the tests prove beyond "it returns 200"

- **Query counts.** A fixture records every statement sent to PostgreSQL. The orders list runs 2 queries and the detail 3, whatever the page size or the number of items. Model relationships use `lazy="raise"`, so an accidental lazy load fails instead of adding a query per row.
- **Keyset pagination.** A walk over every page of deliberately tied data, for both sorts, several page sizes and several filter sets, returns each order exactly once.
- **The read-only role on its own.** `test_readonly_role.py` logs in as `datapilot_readonly` with no guard in front and shows that writes, DDL, reads of real tables, file access and `SET ROLE` are refused, even inside a transaction made read-write.
- **The SQL guard.** Written test first (71 of the first 86 cases failed against a guard that accepted everything). Every query the guard accepts is also run on PostgreSQL, because the guard regenerates SQL rather than passing the model's text through.
- **Errors and outages.** Error responses are checked for their status, envelope and request id. Redis and PostgreSQL outages are simulated and must give `503 service_unavailable`, and a statement over the 3-second cap must give `503 statement_timeout`.
- **Determinism.** A golden checksum pins the seed generator's exact output at a tiny scale.
- **Plans, not only results.** `scripts/explain_orders.py` and `scripts/explain_analytics.py` are tested on a small dataset, and a test pins the extended statistics object to the exact expression in `revenue_monthly.sql`, so a rewrite of the expression cannot silently slow the query.

### No external calls

Tests never reach a model provider. The Ask service is tested with `FakeLLMClient`, which answers the example questions with fixed SQL, and with scripted clients (`ScriptedLLMClient`) that answer or fail in a given order to drive the fallback and repair paths. The real provider clients run against an in-process mock HTTP transport, so the tests see the exact requests the SDKs would send and choose every response, including 401, 429 and 5xx. `filterwarnings = ["error"]` turns any warning into a failure.

Time is injected too: `app.clock` is pinned in tests that depend on today's date, and the rate limiter's clock is pinned to the start of a window.

## Frontend

Unit tests cover what holds logic: services and their HTTP calls (`HttpTestingController`), the signal stores, the auth interceptor (one shared refresh for concurrent 401s, retry, logout on a rejected refresh), the guards, formatting, and the components' loading, empty and error states. Chart.js is replaced by a factory that records each chart's configuration (`provideFakeCharts`), because jsdom has no canvas; deferred blocks are driven manually so the tests do not depend on timing. API models mirror the backend's `Out` schemas, and the tests use the same JSON shapes the API returns.

## End to end

`e2e/tests/smoke.spec.ts` runs against the demo stack built from the production images: log in with the demo account, reload (the refresh cookie must restore the session), open the orders and one order, and ask an example question with the demo model. It is one test on purpose. Its job is to prove that the images, Nginx, the cookies, the Content-Security-Policy and the database roles work together, which no unit test can, and to stay fast and stable enough to gate every pull request.

## Running the tests

```bash
make up            # PostgreSQL and Redis for the backend tests
make check         # lint, types and tests for backend and frontend, and the e2e type check
make be-test       # backend tests only, with coverage
make fe-test       # frontend tests only, with coverage

make demo          # the production-like stack
make e2e-install   # once: the smoke test's dependencies and Chromium
make e2e           # the browser smoke test against the running stack
```
