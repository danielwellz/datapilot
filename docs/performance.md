# Performance

DataPilot must stay fast on the full dataset: 2,000,000 orders, 4,478,509 order items and 50,000 customers. The target for the orders list and detail is a **p95 under 150 ms**, uncached, on a laptop. This document records how the orders endpoints were measured, which indexes were added and why, and the results before and after.

## Results

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

## How it was measured

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

## What changed in the plans

**Before.** PostgreSQL had only primary keys, so it could not find the newest orders without looking at all of them. Every list query became a parallel sequential scan of all 2 million orders: three processes each read a third of the table, joined every row to its customer, and kept the 26 best rows in a "top-N" sort. Showing 25 orders meant reading 2 million.

**After.** An index stores the orders already sorted by the indexed columns. "The 26 newest orders" becomes "start at the end of the `(created_at, id)` index and read backwards 26 entries". Each of those rows then fetches its customer through the customers primary key. The work no longer depends on the size of the table, only on the size of the page.

**Customer history.** Before, the planner scanned the whole orders table to find one customer's 1,446 orders. The index `(customer_id, created_at, id)` keeps each customer's orders together, already sorted by date. The query jumps to that customer and reads the newest 26.

**Country and date filters.** The country is a column of `customers`, not `orders`. The plan walks orders newest first in the date range and checks each order's customer. That is fast as long as matching orders are common enough: for DE, the 26 matches were found after 256 orders. PostgreSQL caches customer lookups (`Memoize`), so a repeat customer is read once.

## The indexes and why each one exists

All three are on `orders`, are built with `CREATE INDEX CONCURRENTLY` (writes are not blocked during the build), and end with `id`. The `id` makes every position unique, which keyset pagination needs (see [ADR 0005](adr/0005-keyset-pagination.md)): a cursor holds the last row's sort value and id, and the next page is a seek into the index to "just after that pair".

| Index | Size | Build time | Used by |
| --- | ---: | ---: | --- |
| `ix_orders_created_at_id (created_at, id)` | 60 MB | 0.4 s | Default list, every deeper page, date ranges, country filter, min and max order date in `/api/meta` |
| `ix_orders_total_id (total, id)` | 60 MB | 1.0 s | The list with `sort=total`; also used by selective `min_total` filters |
| `ix_orders_customer_id_created_at_id (customer_id, created_at, id)` | 77 MB | 0.7 s | A customer's orders, newest first; also any lookup of orders by customer |

The indexes are ascending. A B-tree is read backwards as efficiently as forwards ("Index Scan Backward" in the plans), so the descending sorts need no `DESC` index. Ascending definitions also keep Alembic's autogenerate comparison stable.

Build times are from the first, hand-run builds on the full dataset; the migration that creates all three took 2.6 s. The cost is about 200 MB of disk and a little extra work on every insert into `orders`. That trade suits an analytics store, which reads far more than it writes.

## Indexes considered and left out

Each one was built on the full dataset, measured, and dropped again:

- **`customers (country)`**, suggested for the country filter. The filter never used it: the plan reaches each customer through the primary key while walking orders by date, so an index on country has nothing to do there. The only query that used it was the list of distinct countries in `/api/meta`, which dropped from 5.4 ms to 3.2 ms. That is not worth a permanent index.
- **`orders (status, created_at, id)`**, for rare status filters. With it, "cancelled orders from DK" dropped from 8.95 ms to 2.6 ms. That query is already 17 times under the target, while the index would add 60 MB and work on every insert. It can be added later if a measured query needs it.
- **A partial index on paid orders** belongs to the analytics queries of the next stage, where a plan can prove it is needed.
- **`order_items (product_id)`** was not used by any orders endpoint. The detail reads items through the primary key `(order_id, product_id)`.

## Keyset compared with OFFSET at depth

Both scenarios return the same 26 rows, those after row 1,000,000:

| | Before indexes | After indexes |
| --- | ---: | ---: |
| Keyset cursor (what the API runs) | 133.15 ms | **0.18 ms** |
| `OFFSET 1000000` | 483.51 ms | 303.04 ms |

With OFFSET, PostgreSQL still has to produce the first 1,000,000 rows and throw them away. With the index it walks them instead of sorting them, but it also joins each of them to its customer: 159,606 buffer reads to return 26 rows. Its cost grows with the page number. The keyset query seeks straight to the position the cursor names, reads 82 buffers, and costs the same on page 1 as on page 40,000. The API therefore offers only cursor pagination.

## Worst cases

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
3. A statement timeout on the list query.

## Query counts

The list runs **2 queries** per request whatever the page size: the token's user, then the page of orders joined to their customers. The detail runs **3**: the user, the order joined to its customer, and the items joined to their products. Integration tests assert these counts at page sizes 1 and 100, and for orders with 1 and 10 items, using a fixture that records every statement sent to PostgreSQL. Model relationships use `lazy="raise"`, so an accidental lazy load fails a test instead of adding a query per row.
