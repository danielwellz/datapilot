# 6. Analytics in SQL files, cached in Redis by data version

- Status: Accepted
- Date: 2026-10-08

## Context

The dashboard needs five views of 2 million orders: a period summary, monthly revenue with month-over-month and year-over-year change, top customers per country, a product ranking with category shares, and retention cohorts. Each one aggregates hundreds of thousands to millions of rows. Uncached, the slowest of them took up to 800 ms on the full dataset; the target is under 800 ms uncached and under 50 ms cached. The numbers must be exactly right, including ties, months without sales and UTC period boundaries.

Three questions needed an answer:

1. **Where the queries live and how they are written.** The options were the SQLAlchemy expression language, an ORM query per view, or plain SQL.
2. **What a "period" is.** The options were to include today and the current month, or to report only complete days and months.
3. **How results are cached.** The options were no cache, an HTTP cache in front of the API, a materialized view per query, or cache-aside in Redis.

## Decision

### Queries are plain SQL files

Each query is one file in `backend/app/analytics/sql/`, with a header comment that says what it returns and lists its parameters. The files are read once at import (`app/analytics/queries.py`) and run with SQLAlchemy `text()` and named bind parameters. Values never reach the SQL text, and a test checks that no file contains a placeholder a Python formatter could fill.

These queries are window functions over CTEs: `lag()` for the month and year comparisons, a `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` frame for the moving average, `dense_rank()` partitioned by country, `sum() OVER (PARTITION BY category)` for shares, and `row_number()` over a month grid for cohort offsets. Written as SQL, they can be read, formatted and run in `psql` exactly as the API runs them. Written in the expression language, they would be harder to read than the SQL they produce.

Column names in each file match the fields of its Pydantic response model, so the service validates rows straight into responses. Exact expected numbers are asserted in integration tests on small hand-built datasets: ties in both rankings, a month with zero revenue, a refund kept out of revenue, a catalog price changed after the sale, and orders one second either side of each period boundary, including ones written with a non-UTC offset.

### Only complete UTC periods are reported

`days=N` means the N whole UTC days ending yesterday; `months=M` means the M calendar months before the current one. A period that included today would always look like a drop against a complete one. The date comes from `app.clock.utc_today()`, which tests pin. Month boundaries are computed with `AT TIME ZONE 'UTC'`, so the session's time zone cannot move an order into another month.

Revenue counts paid orders only. "Orders" and the average order value use paid orders too, so the average is revenue divided by orders. The refund rate is refunded orders divided by all orders placed in the period.

### Cache-aside in Redis, keyed by data version

`ResponseCache` (`app/services/cache.py`) stores serialized response bodies under keys of this form:

```
cache:analytics:summary:v812:as_of=2026-10-08&days=30
```

- **Data version.** Every seed bumps `data_version` in Redis after it commits. A new dataset therefore gets new keys at once. The old entries are never read again and expire on their own, so nothing has to scan for keys or delete them.
- **Normalized parameters.** The key holds the validated query model with its defaults filled in, sorted and URL-encoded. `?days=30` and no parameter share an entry, `country=us` and `country=US` share one, and a category containing `&` cannot be confused with a separator.
- **Today's date.** The analytics keys contain `as_of`, because yesterday's periods are different from today's.
- **TTL of 10 minutes.** This bounds how long an entry can outlive a change that did not bump the version.
- **Stampede lock.** On a miss, only the request that wins `SET lock:<key> <token> NX PX 5000` computes. The others poll for its result every 25 ms for up to 3 s, then compute themselves rather than wait longer. The lock is released with a compare-and-delete Lua script, so a holder whose lock expired never deletes a lock someone else took over.
- **`X-Cache` header.** Every response says `HIT`, `MISS` or `BYPASS`.

Only successful bodies are stored. Validation errors and unauthenticated requests never reach the cache. Entries are shared by every user, which is correct because analytics data is not per user. `/api/meta` uses the same cache, keyed by data version only.

### The cache fails open, unlike login rate limiting

When Redis is unreachable, the cache logs a warning, computes the response and answers `X-Cache: BYPASS`. Login rate limiting (ADR 0003) fails closed instead, with a 500, when Redis is down. The difference is deliberate:

- **Rate limiting is a security control.** Skipping it during an outage would open login to unlimited password guessing exactly when monitoring is weakest.
- **The cache is only a performance aid.** Every uncached query meets its target, so serving uncached is slower but correct. Failing analytics requests because the cache is missing would turn a performance problem into an outage.

### Tuning measured on the full dataset

Three queries were slower than they needed to be. Each fix was measured before and after (`docs/performance.md`):

- **Summary.** `count(DISTINCT customer_id)` sorted every order of both periods in one process. Grouping by customer first allows a parallel aggregate: 682 to 321 ms for 365 days.
- **Monthly revenue.** PostgreSQL keeps no statistics on expressions, so it expected 1.86 million groups for the month expression instead of 36 and chose a serial plan. Extended statistics on that exact expression (`st_orders_created_month_utc`): 492 to 152 ms.
- **Cohorts.** At 24 months the query fetched 1.39 million order rows only to check their status: 818 ms, over the target. A partial index on `(customer_id, created_at) WHERE status = 'paid'` lets it read the index alone: 338 ms, and 73 ms for the default 12 months.

## Alternatives rejected

- **SQLAlchemy expressions or ORM queries.** These are harder to read for window-heavy SQL, and the ORM would build objects nobody needs.
- **Materialized views refreshed by the seed.** These make reads nearly free, but every new parameter combination (period length, country, category) needs its own view or a much larger one, and the views add refresh steps to every load. Every query meets its target without them.
- **An HTTP cache (`Cache-Control`, a reverse proxy).** The API needs a bearer token, so shared HTTP caches would not store the responses. It also cannot be invalidated by data version.
- **Deleting keys on reseed** (`SCAN` plus `DEL`). This costs more than versioned keys, and it races with requests that are filling entries while the seed runs.
- **`NOT MATERIALIZED` on the cohort members CTE.** This fixed the 24-month cohorts (531 ms) but slowed the default 12 months from 243 to 306 ms. The index helps both.

## Consequences

- **Cached responses take 2.5 to 8.9 ms at p95. Uncached, the slowest endpoint (the product ranking) takes 423 ms** (`docs/performance.md`).
- **Every dashboard number changes as soon as the data is reseeded.** Otherwise, numbers can be up to 10 minutes old.
- **Key space.** A client can enumerate parameter combinations (365 day counts × 21 countries × 100 limits) and fill Redis with entries for 10 minutes each. Only authenticated users can do this. Stage 11 should set Redis `maxmemory` with `volatile-lru`, so cache entries are evicted before anything else.
- **The paid orders index costs 57 MB, and work on every insert of a paid order.** It is read as an index-only scan only after vacuum has marked the table's pages all-visible. Right after a seed, cohorts at 24 months take about 750 ms until autovacuum runs.
- **Matching expressions.** The month statistics apply only to the identical expression. A test pins the statistics object and the expression in `revenue_monthly.sql`, so a rewrite of that expression fails the test instead of silently slowing the query.

## Later changes

- **2026-10-09 (Stage 11):** login now fails closed with `503 service_unavailable` instead of a 500 when Redis is down. The cache still fails open with `X-Cache: BYPASS`.
- **2026-10-09 (Stage 11):** Redis runs with `maxmemory 256mb` and `volatile-lru` in development and in the demo stack.
- **2026-10-09 (Stage 11):** the seed writes frozen, all-visible pages (ADR 0004), so the cohorts query reads the paid orders index alone right after a seed instead of waiting for autovacuum.
