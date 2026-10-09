# Performance

DataPilot must stay fast on the full dataset: 2,000,000 orders, 4,478,509 order items and 50,000 customers. The targets, on a laptop, are:

- **Orders list and detail:** p95 under 150 ms, uncached.
- **Analytics endpoints:** under 50 ms cached and under 800 ms uncached.

This document records how each was measured, what was changed and why, and the results before and after. [Current numbers](#current-numbers) is the latest run of every endpoint; the orders endpoints' history follows, then the analytics endpoints in [Analytics endpoints](#analytics-endpoints).

## Current numbers

`make bench` (`scripts/bench_suite.py`) measures every latency the README reports in one run: it logs in once, takes the data's last day and highest order id from the API, and sends each row's requests one after another over one keep-alive connection, after a warm-up. Uncached analytics rows bump `data_version` before each request, outside the timing, and the script stops unless every timed reply carried the expected `X-Cache` value (`MISS` for uncached rows, `HIT` for cached ones).

Run on 2026-10-09: full dataset (seed 42, history ending 2026-10-07), Gunicorn with 2 workers of 4 threads (`gunicorn.conf.py`), same machine and Docker settings as below.

| Request | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| `GET /api/orders` (first page, newest first) | 2.9 ms | **4.4 ms** | 5.1 ms |
| `GET /api/orders?limit=25`, following `next_cursor` page after page | 2.9 ms | **3.5 ms** | 4.5 ms |
| `GET /api/orders?country=DE&date_from=2026-07-09` | 3.1 ms | **4.9 ms** | 5.7 ms |
| `GET /api/orders?customer_id=5880` (the busiest customer) | 2.6 ms | **3.7 ms** | 4.8 ms |
| `GET /api/orders/{id}` (1,000 random ids) | 2.9 ms | **3.3 ms** | 4.9 ms |

| Analytics request | Uncached p50 | **Uncached p95** | **Cached p95** |
| --- | ---: | ---: | ---: |
| `/api/analytics/summary` (30 days) | 58.8 ms | **60.6 ms** | **2.5 ms** |
| `/api/analytics/summary?days=365` | 285.5 ms | **339.4 ms** | **3.2 ms** |
| `/api/analytics/revenue-monthly` (24 months) | 133.5 ms | **137.2 ms** | **3.4 ms** |
| `/api/analytics/revenue-monthly?months=36` | 138.7 ms | **153.1 ms** | **2.9 ms** |
| `/api/analytics/top-customers` (365 days) | 195.4 ms | **242.3 ms** | **3.8 ms** |
| `/api/analytics/products` (365 days) | 413.3 ms | **479.1 ms** | **3.1 ms** |
| `/api/analytics/cohorts` (12 months) | 65.3 ms | **69.1 ms** | **2.6 ms** |
| `/api/analytics/cohorts?months=24` | 239.2 ms | **246.7 ms** | **2.9 ms** |
| `/api/meta` | 7.3 ms | **9.4 ms** | **2.9 ms** |

Uncached rows are 50 requests after 3 warm-up requests; every other row is 500 requests (1,000 for the detail) after a warm-up. Every row meets its target: orders under 150 ms, analytics under 800 ms uncached and under 50 ms cached.

- **Orders** are two to three times faster than in the Stage 4 measurements below (p95 7.3 to 12.8 ms then). The stack changed in between: threaded Gunicorn workers, and indexes rebuilt after the seed, which also leaves the pages all-visible ([ADR 0004](adr/0004-deterministic-seed-data.md)). The runs were not repeated for each change, so the difference is not attributed to one of them.
- **Analytics** uncached numbers are within run-to-run variation of the Stage 5 measurements, except the product ranking and the top customers, which vary the most because they read all of `order_items` or a year of orders.
- **One outlier:** one cached `summary?days=365` request took 5.7 s at the client, while its p99 stayed at 7.7 ms. The server logged no request of that length, and 5,000 further requests to the same endpoint, across worker restarts, had a maximum of 38 ms. It was a stall outside the API and is left out of the conclusions.

The same suite through Nginx on the demo stack loaded with the full dataset (`make demo scale=full`, then `make bench args="--base-url http://localhost:8080 --skip-uncached"`) gave p95 1.9 to 2.6 ms for every orders row and 1.5 to 2.4 ms for every cached analytics row. The demo's PostgreSQL has larger `shared_buffers` and `work_mem`. The uncached rows cannot run there, because the demo's Redis is not published on the host.

To reproduce, with the development services up (`make up`, `make db-upgrade`, `make db-roles`):

```bash
make seed scale=full
cd backend && uv run gunicorn --bind 127.0.0.1:5001 "app:create_app()"
make bench                         # in a second terminal, about 2 minutes
```

## Orders endpoints

### Results (Stage 4)

API latency, measured by `scripts/bench_api.py`. Each row is 500 sequential requests (1,000 for the detail) after a warm-up, sent over one keep-alive connection to gunicorn with 2 workers.

| Request | p50 before | p95 before | p50 after | p95 after | p99 after |
| --- | ---: | ---: | ---: | ---: | ---: |
| `GET /api/orders` (first page, newest first) | 178.1 ms | 188.6 ms | 7.5 ms | **8.9 ms** | 10.7 ms |
| `GET /api/orders?limit=25`, following `next_cursor` page after page | 192.6 ms | 206.3 ms | 4.1 ms | **8.5 ms** | 9.4 ms |
| `GET /api/orders?country=DE&date_from=2026-07-09` | 39.1 ms | 41.8 ms | 10.5 ms | **12.8 ms** | 14.2 ms |
| `GET /api/orders?customer_id=5880` (the busiest customer, 1,446 orders) | 26.5 ms | 28.5 ms | 4.6 ms | **7.3 ms** | 8.0 ms |
| `GET /api/orders/{id}` (random ids) | 5.2 ms | 9.1 ms | 7.4 ms | **9.2 ms** | 9.9 ms |

Every endpoint is now far under the 150 ms target. Before the indexes, the first page of the list (p95 189 ms) and paging with the cursor (p95 206 ms) both missed it. The detail was already fast, because it reads orders and items by primary key. Its small change is noise between runs. The slowest detail request in the after run took 52 ms, while its p99 stayed at 9.9 ms.

The cost inside PostgreSQL, from `scripts/explain_orders.py`, is the median `EXPLAIN (ANALYZE, BUFFERS)` execution time over 10 runs:

| Scenario | Before | After | Plan after |
| --- | ---: | ---: | --- |
| `list-default`: first page, newest first | 226.85 ms | 0.19 ms | Backward index scan on `(created_at, id)`, stops after 26 rows |
| `list-country-90-days`: country DE, last 90 days | 37.64 ms | 0.35 ms | Same index, skips orders whose customer is not in DE |
| `list-customer-history`: busiest customer | 25.20 ms | 0.03 ms | Backward index scan on `(customer_id, created_at, id)` |
| `list-by-total`: first page, largest first | 214.60 ms | 0.18 ms | Backward index scan on `(total, id)` |
| `list-deep-keyset`: page after row 1,000,000, keyset | 133.15 ms | 0.18 ms | Seeks into `(created_at, id)`, reads 26 rows |
| `list-deep-offset`: same page with `OFFSET 1000000` | 483.51 ms | 303.04 ms | Reads and discards 1,000,000 index entries first |
| `list-rare-filters`: cancelled orders from DK | 30.67 ms | 8.95 ms | Walks `(created_at, id)`, filtering out 154,551 rows |
| `order-detail`: order, customer, items (2 queries) | 0.10 ms | 0.09 ms | Primary keys only, unchanged |
| `meta`: date bounds, countries, categories (3 queries) | 65.84 ms | 4.90 ms | Date bounds read from both ends of `(created_at, id)` |

EXPLAIN ANALYZE times every plan node, which adds overhead when millions of rows flow through a plan. That is why the slow "before" plans take longer here (227 ms) than through the API (178 ms).

### How it was measured

- **Machine:** Apple M4 laptop. PostgreSQL 16.15 and Redis 7 run in Docker Desktop with default settings (`shared_buffers=128MB`, `work_mem=4MB`, `jit=on`, 2 parallel workers per gather).
- **Data:** `make seed scale=full` with seed 42 and history ending 2026-10-07. `ANALYZE` ran during the seed, and autovacuum had processed every table before the first measurement.
- **Order of work:** the scripts were committed first. The baseline was then captured with only primary-key and unique indexes, the indexes were added in a separate migration, and the same commands ran again. The git history shows that order.
- **Warm cache:** each EXPLAIN scenario runs once unmeasured, then 10 measured times, so every run finds the same pages in memory. The orders table (185 MB with its primary key) is larger than `shared_buffers`, so the "read" buffers in the baseline come from the operating system's cache, not from disk.
- **Same SQL as the API:** `explain_orders.py` calls the repository methods the API calls, records the statements they send, and explains those statements with their real parameters. The only hand-built query is the OFFSET comparison, which the API never runs.

To reproduce:

```bash
make seed scale=full
make explain                       # EXPLAIN scenarios on the dev database
cd backend && uv run gunicorn --workers 2 --bind 127.0.0.1:5001 "app:create_app()"
# in a second terminal, from backend/:
uv run python -m scripts.bench_api --path "/api/orders" -n 500 --warmup 20
uv run python -m scripts.bench_api --path "/api/orders?limit=25" --follow-cursor -n 500 --warmup 20
uv run python -m scripts.bench_api --path "/api/orders/{order_id}" --max-order-id 2000000 -n 1000
```

### What changed in the plans

**Before.** PostgreSQL had only primary keys, so it could not find the newest orders without looking at all of them. Every list query became a parallel sequential scan of all 2 million orders: three processes each read a third of the table, joined every row to its customer, and kept the 26 best rows in a "top-N" sort. Showing 25 orders meant reading 2 million.

**After.** An index stores the orders already sorted by the indexed columns. "The 26 newest orders" becomes "start at the end of the `(created_at, id)` index and read backwards 26 entries". Each of those rows then fetches its customer through the customers primary key. The work no longer depends on the size of the table, only on the size of the page.

**Customer history.** Before, the planner scanned the whole orders table to find one customer's 1,446 orders. The index `(customer_id, created_at, id)` keeps each customer's orders together, already sorted by date. The query jumps to that customer and reads the newest 26.

**Country and date filters.** The country is a column of `customers`, not `orders`. The plan walks orders newest first in the date range and checks each order's customer. That is fast as long as matching orders are common enough: for DE, the 26 matches were found after 256 orders. PostgreSQL caches customer lookups (`Memoize`), so a repeat customer is read once.

### The indexes and why each one exists

All three are on `orders`, are built with `CREATE INDEX CONCURRENTLY` (writes are not blocked during the build), and end with `id`. The `id` makes every position unique, which keyset pagination needs (see [ADR 0005](adr/0005-keyset-pagination.md)): a cursor holds the last row's sort value and id, and the next page is a seek into the index to "just after that pair".

| Index | Size | Build time | Used by |
| --- | ---: | ---: | --- |
| `ix_orders_created_at_id (created_at, id)` | 60 MB | 0.4 s | Default list, every deeper page, date ranges, country filter, min and max order date in `/api/meta` |
| `ix_orders_total_id (total, id)` | 60 MB | 1.0 s | The list with `sort=total`; also used by selective `min_total` filters |
| `ix_orders_customer_id_created_at_id (customer_id, created_at, id)` | 77 MB | 0.7 s | A customer's orders, newest first; also any lookup of orders by customer |

The indexes are ascending. A B-tree is read backwards as efficiently as forwards ("Index Scan Backward" in the plans), so the descending sorts need no `DESC` index. Ascending definitions also keep Alembic's autogenerate comparison stable.

Build times are from the first, hand-run builds on the full dataset; the migration that creates all three took 2.6 s. The cost is about 200 MB of disk and a little extra work on every insert into `orders`. That trade suits an analytics store, which reads far more than it writes.

### Indexes considered and left out

Each one was built on the full dataset, measured, and dropped again:

- **`customers (country)`**, suggested for the country filter. The filter never used it: the plan reaches each customer through the primary key while walking orders by date, so an index on country has nothing to do there. The only query that used it was the list of distinct countries in `/api/meta`, which dropped from 5.4 ms to 3.2 ms. That is not worth a permanent index.
- **`orders (status, created_at, id)`**, for rare status filters. With it, "cancelled orders from DK" dropped from 8.95 ms to 2.6 ms. That query is already 17 times under the target, while the index would add 60 MB and work on every insert. It can be added later if a measured query needs it.
- **A partial index on paid orders** was left to the analytics queries, where a plan could prove it was needed. One did: see [Cohorts](#cohorts-a-partial-index-for-an-index-only-join).
- **`order_items (product_id)`** was not used by any orders endpoint. The detail reads items through the primary key `(order_id, product_id)`.

### Keyset compared with OFFSET at depth

Both scenarios return the same 26 rows, those after row 1,000,000:

| | Before indexes | After indexes |
| --- | ---: | ---: |
| Keyset cursor (what the API runs) | 133.15 ms | **0.18 ms** |
| `OFFSET 1000000` | 483.51 ms | 303.04 ms |

With OFFSET, PostgreSQL still has to produce the first 1,000,000 rows and throw them away. With the index it walks them instead of sorting them, but it also joins each of them to its customer: 159,606 buffer reads to return 26 rows. Its cost grows with the page number. The keyset query seeks straight to the position the cursor names, reads 82 buffers, and costs the same on page 1 as on page 40,000. The API therefore offers only cursor pagination.

### Worst cases

The list is fast when the plan finds a page of matches quickly. The risk is a combination of filters so rare that walking the date index finds few or no matches and reads far into the table. These combinations were measured through the API after the indexes, 3 requests each:

| Filters | Matches on the page | Time |
| --- | ---: | ---: |
| `status=cancelled&channel=marketplace&country=DK` | 25 | 30 to 58 ms |
| `min_total=2000` (154 orders in total) | 25 | 22 to 45 ms |
| `status=cancelled&country=DK&min_total=500` (2 orders in total) | 2 | 12 to 15 ms |
| `sort=total` with two statuses, DE, web, September 2026 and totals 100 to 200 (35 orders in total) | 4 | 34 to 38 ms; 132 ms on the first, cold request |
| `min_total=4000` (no matching orders) | 0 | 3 ms |
| `country=ZZ` (no matching customers) | 0 | 4 to 5 ms |

For a selective `min_total`, the planner switches to a range read on `(total, id)` followed by a sort, rather than walking the date index. The slowest case found sorts by total inside a total range and filters on four other columns. It walks `(total, id)` from 200 down and discards 68,788 rows to fill the page. The first request read pages that were not yet in memory (132 ms); repeats took 34 to 38 ms. Every case stays under the target, the cold one included. If a future filter makes this worse, the remedies are, in order:

1. An index that matches the filter, such as `(status, created_at, id)`.
2. Copying the customer's country onto `orders`, as an expand/contract migration.
3. A statement timeout on the list query. Since Stage 11, every statement an API request runs is cancelled after 3 seconds (`API_STATEMENT_TIMEOUT_MS`), with `503 statement_timeout`, as a backstop.

### Query counts

The list runs **2 queries** per request whatever the page size: the token's user, then the page of orders joined to their customers. The detail runs **3**: the user, the order joined to its customer, and the items joined to their products. Integration tests assert these counts at page sizes 1 and 100, and for orders with 1 and 10 items, using a fixture that records every statement sent to PostgreSQL. Model relationships use `lazy="raise"`, so an accidental lazy load fails a test instead of adding a query per row.

## Analytics endpoints

The five analytics endpoints and `/api/meta` are answered through a Redis cache-aside layer ([ADR 0006](adr/0006-analytics-sql-and-caching.md)). A cached request reads one entry from Redis. An uncached request runs one analytics query, which aggregates hundreds of thousands to millions of rows. Both kinds are measured below.

### Results (Stage 5)

API latency from `scripts/bench_api.py` against gunicorn with 2 workers, sequential requests over one keep-alive connection:

- **Uncached:** 50 requests after 3 warm-up requests, with `--invalidate-cache`, which bumps `data_version` before each request (outside the timing), so every request misses.
- **Cached:** 500 requests after 50 warm-up requests.
- **Proof of kind:** the script counted the `X-Cache` header of every timed response. It was `MISS` for all 50 uncached requests and `HIT` for all 500 cached ones, in every row.

| Request | Uncached p95 before | Uncached p50 after | **Uncached p95 after** | Uncached p99 after | **Cached p95** |
| --- | ---: | ---: | ---: | ---: | ---: |
| `/api/analytics/summary` (30 days) | 116.1 ms | 62.0 ms | **68.3 ms** | 89.7 ms | **2.7 ms** |
| `/api/analytics/summary?days=365` | 614.7 ms | 294.7 ms | **313.7 ms** | 329.5 ms | **3.3 ms** |
| `/api/analytics/revenue-monthly` (24 months) | 481.7 ms | 141.7 ms | **148.3 ms** | 152.9 ms | **2.8 ms** |
| `/api/analytics/revenue-monthly?months=36` | 462.6 ms | 141.9 ms | **149.1 ms** | 157.6 ms | **8.9 ms** |
| `/api/analytics/top-customers` (365 days) | 212.1 ms | 194.7 ms | **199.7 ms** | 221.7 ms | **2.5 ms** |
| `/api/analytics/products` (365 days) | 438.4 ms | 397.0 ms | **423.0 ms** | 425.8 ms | **2.7 ms** |
| `/api/analytics/cohorts` (12 months) | 224.6 ms | 66.6 ms | **69.4 ms** | 71.9 ms | **2.9 ms** |
| `/api/analytics/cohorts?months=24` | 795.5 ms | 237.2 ms | **248.4 ms** | 265.9 ms | **5.8 ms** |
| `/api/meta` | 9.4 ms | 7.0 ms | **9.2 ms** | 16.0 ms | **2.8 ms** |

Every endpoint meets both targets:

- **Uncached:** under 800 ms, with the slowest, the product ranking, at 423 ms. Before the tuning, the 24-month cohorts reached 796 ms at p95 and 864 ms at the maximum.
- **Cached:** p95 between 2.5 and 8.9 ms, against a 50 ms target.

A hit costs two Redis reads (the data version and the entry) and one validation of the stored JSON against the response model. The "before" column is the same benchmark, run before the three changes below.

**Stampede lock under load.** Right after a `data_version` bump, 8 concurrent requests for `/api/analytics/cohorts?months=24` returned 1 `MISS` and 7 `HIT`, all within 283 to 300 ms. One request ran the query, and the others waited for its result instead of running the same query themselves.

Inside PostgreSQL, from `make explain-analytics` (median `EXPLAIN (ANALYZE, BUFFERS)` execution time over 10 runs, periods ending 2026-10-07):

| Scenario | Before | After | What changed |
| --- | ---: | ---: | --- |
| `summary-30` | 113.96 ms | 61.25 ms | Per-customer grouping |
| `summary-365` | 681.67 ms | 320.85 ms | Per-customer grouping |
| `revenue-monthly-24` | 491.87 ms | 152.21 ms | Statistics on the month expression |
| `revenue-monthly-36` | 494.90 ms | 154.40 ms | Statistics on the month expression |
| `top-customers` (every country) | 204.34 ms | 209.37 ms | Nothing |
| `top-customers-de` | 168.84 ms | 173.03 ms | Nothing |
| `products` | 444.96 ms | 485.38 ms | Nothing |
| `products-category` (Electronics) | 455.88 ms | 497.11 ms | Nothing |
| `cohorts-12` | 243.02 ms | 72.86 ms | Partial index on paid orders |
| `cohorts-24` | 818.42 ms | 338.25 ms | Partial index on paid orders |

The rows marked "Nothing" kept the same plan. Their differences are run-to-run variation. The product ranking reads all of `order_items` (36,000 blocks, mostly from the operating system's cache), so it varies the most.

The "after" runs were taken on a fresh seed of the identical dataset (seed 42, history ending 2026-10-07), after autovacuum had processed it. The reason is given under [After a seed](#after-a-seed).

### Summary: grouping by customer instead of count(DISTINCT)

The first version counted active customers with `count(DISTINCT customer_id) FILTER (WHERE status = 'paid')`. PostgreSQL cannot split a distinct count across parallel workers, so it gathered all 1.47 million orders of the two 365-day periods into one process and sorted them, spilling to disk ("external merge"):

```
Aggregate (rows=2)
  Gather Merge (rows=1474545, workers=2)
    Sort (rows=491515, loops=3, sort=external merge)
      Seq Scan on orders (rows=491515, loops=3, removed by filter=175152)
```

The rewrite first groups the orders by customer and period, then counts those groups. A GROUP BY can be aggregated in parallel: each worker reduces its third of the rows to about 70,000 groups, and only those are merged:

```
Aggregate (rows=2)
  Aggregate (rows=78750)
    Gather Merge (rows=210701, workers=2)
      Sort (rows=70234, loops=3, sort=external merge)
        Aggregate (rows=70234, loops=3)
          Seq Scan on orders (rows=491515, loops=3, removed by filter=175152)
```

Three variants were measured. Grouping by the period label (`'current'` or `'previous'`) gave a serial plan (536 ms). Grouping by the boolean `created_at >= :current_start` gave the parallel plan above (307 ms). One row per customer with separate columns for each period was slower (349 ms) and harder to read. The remaining spill comes from the default `work_mem` of 4 MB; raising it is a server setting, left at its default here.

### Monthly revenue: statistics on an expression

The query groups paid orders by `CAST(date_trunc('month', created_at AT TIME ZONE 'UTC') AS date)`. PostgreSQL keeps statistics per column, not per expression, so it estimated **1,859,612 groups instead of 36**. With that estimate, a parallel partial aggregate looked pointless, and it chose one serial hash aggregate planned for 128 partitions:

```
HashAggregate  (rows=1859612 estimated, 36 actual)
  ->  Seq Scan on orders  (rows=1883204)
```

The migration `239eec08d96c` adds extended statistics on exactly that expression (`st_orders_created_month_utc`) and analyses the table. The estimate became 37 (the data spans 37 months), and the planner chose a parallel partial aggregate:

```
Finalize GroupAggregate (rows=36)
  Gather Merge (rows=106, workers=2)
    Sort (rows=35, loops=3)
      Partial HashAggregate (rows=35, loops=3)
        Parallel Seq Scan on orders (rows=627735, loops=3)
```

The statistics object costs nothing on writes. The seed already runs `ANALYZE` after each load, which refreshes it; a fresh seed was checked and estimated 37 months. The planner uses it only for an identical expression, so `test_orders_have_statistics_on_the_month_the_revenue_query_groups_by` pins both the object and the expression in `revenue_monthly.sql`.

### Cohorts: a partial index for an index-only join

At 24 months, the cohort query joins 31,117 customers to their paid orders over two years. The planner merged them through `ix_orders_customer_id_created_at_id`, which does not contain `status`. It therefore fetched 1.39 million order rows from the table only to check that each order was paid: 1,456,537 buffer hits and 818 ms, over the target.

The migration `959f4df99a26` adds `ix_orders_paid_customer_id_created_at`, on `(customer_id, created_at) WHERE status = 'paid'`. It holds everything the join reads, so the join becomes an index-only scan that never visits the table:

```
Merge Join (rows=563921)
  Index Only Scan using ix_orders_paid_customer_id_created_at on orders (rows=1394865)  -- heap fetches: 0
  Sort (rows=566264)
    CTE Scan (rows=31117)
```

| | Without the index | With it |
| --- | ---: | ---: |
| 12 months (default) | 243 ms | 73 ms |
| 24 months | 818 ms | 338 ms |

The index is built concurrently, in 1.4 s on the full dataset. It is 57 MB when built, and 79 MB after a seed, which maintains it row by row. Every other analytics scenario was measured with and without it and kept the same plan and time.

The alternative measured first was `NOT MATERIALIZED` on the cohort members CTE. That CTE is referenced twice, so PostgreSQL computes it once and hides its row estimates from the join. Inlined, it allowed a hash join: 531 ms at 24 months. But the default 12 months slowed from 243 to 306 ms, because the inlined plan went parallel with a sort that spilled to disk. Collapsing the paid orders to distinct customer-months before the join was measured too (375 ms and 535 ms). The index made both cases faster, so it was adopted and the CTE left unchanged.

### After a seed

An index-only scan reads the table after all for any page that the visibility map does not mark all-visible, and only vacuum sets those marks. A seed loads 2 million new rows, so immediately afterwards no page is all-visible (`relallvisible = 0`). This was measured on a fresh seed:

| Scenario | Right after the seed | After autovacuum |
| --- | ---: | ---: |
| `cohorts-12` | 282.83 ms | 72.86 ms |
| `cohorts-24` | 747.00 ms | 338.25 ms |

Autovacuum's insert-triggered vacuum ran about 1.5 minutes after the seed finished. Even before it, every query stays under the 800 ms target. The cache also means a cold query is paid once per entry, not once per request.

Since Stage 11, the seed writes its rows with `COPY ... FREEZE` into the tables it truncated, so about 97% of the pages are all-visible straight after the load ([ADR 0004](adr/0004-deterministic-seed-data.md)), and the index-only scan works without waiting for autovacuum. The measurements above were taken before that change.

### Reproduce

`make bench` runs every row of the results table (see [Current numbers](#current-numbers)). One endpoint at a time:

```bash
make explain-analytics                      # EXPLAIN scenarios on the dev database
cd backend && uv run gunicorn --workers 2 --bind 127.0.0.1:5001 "app:create_app()"
# in a second terminal, from backend/:
uv run python -m scripts.bench_api --path "/api/analytics/cohorts?months=24" -n 50 --warmup 3 --invalidate-cache
uv run python -m scripts.bench_api --path "/api/analytics/cohorts?months=24" -n 500 --warmup 50
```

`--invalidate-cache` bumps `data_version`, which invalidates every cached response, so use it only against a development stack. Login is limited to 5 attempts per minute per address and email, so space out repeated runs.
