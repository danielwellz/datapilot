# 4. Deterministic synthetic sales data loaded with COPY

- Status: Accepted
- Date: 2026-10-08

## Context

The orders explorer, the analytics dashboard and Ask your data all need a sales dataset that is large enough for performance work to mean something (about 2 million orders and 4.5 million order items) and realistic enough that charts and rankings look like a real store. Two people running the seed, or one test running it twice, must get the same rows. A full seed must finish in under 4 minutes on an Apple Silicon laptop.

The options considered were:

- **A public dataset** (for example a Kaggle e-commerce export): real, but fixed in size, licensed separately, not under our control for dates or distributions, and a large download.
- **Faker-style row generation with `INSERT`**: easy to write, but one round trip or one statement per row is far too slow for millions of rows, and Faker's output varies between library versions.
- **SQL-side generation (`generate_series` and `random()`)**: fast, but the distributions become hard to read and test, and `setseed()` reproducibility depends on the server version.
- **A small Python generator streaming into `COPY`**: the option chosen here.

## Decision

**Generation (`backend/app/seed/`)** is plain Python driven by a single `random.Random(seed)`:

- `calendar.py` spreads the requested number of orders over three years of days. A day's volume is growth (25% a year) × month factor (November and December peak) × weekday factor. Largest-remainder rounding makes the days add up to exactly the requested total.
- `generator.py` builds customers, products and orders in a fixed order:
  - Customers have Pareto activity weights, which makes a minority of customers place most orders. They can only order after they sign up.
  - Countries are drawn from about 20 weighted ISO codes.
  - Product prices are log-normal per category, and popularity follows Zipf's law.
  - Orders have 1 to 5 distinct products. About 3% are refunded and 2% cancelled, and the mobile share grows over time.
- Money is kept in integer cents until it is written, so an order's total equals the sum of its items exactly.
- Orders are yielded lazily, one day at a time. Memory stays bounded at any scale.

**Inputs that fix the output:** the seed and the end date. The history covers the three years *before* the end date, so a history ending today never contains a future timestamp. The end date defaults to today (UTC) so the demo looks current, and every test passes it explicitly. A golden checksum test pins the exact output at a tiny scale.

**Loading (`loader.py`)** uses psycopg's `COPY ... FROM STDIN` on the session's own connection:

1. `TRUNCATE ... RESTART IDENTITY` and the load run in the caller's transaction. A failed seed therefore leaves the previous data untouched.
2. Customers and products are copied first. Orders and their items are then copied in batches of 50,000 orders: one connection runs one `COPY` at a time, and an order must exist before its items' foreign keys are checked.
3. `COPY` writes the generated ids into the `GENERATED ALWAYS` identity columns (PostgreSQL treats `COPY` like `OVERRIDING SYSTEM VALUE`). `setval` then moves each sequence past the highest id.
4. `ANALYZE` refreshes planner statistics before the commit.

**Seed command (`flask seed`, `make seed`):**

- creates the demo account only when it is missing, and never changes an existing one;
- bumps the `data_version` key in Redis after the commit, so caches keyed on it never pair the new version with the old data;
- prints row counts, table sizes and the elapsed time.

**No performance indexes are added in this stage.** Stage 4 measures query plans before and after adding them.

## Measurements

Apple M4 (10 cores, 16 GB), PostgreSQL 16 in Docker Desktop, seed 42, end date 2026-10-08:

| Step | Time |
| --- | --- |
| Generating the full scale in Python, without I/O | 8.0 s |
| `make seed scale=full` (generation, COPY with foreign keys, ANALYZE, commit) | 93.1 s wall clock, 16.1 s Python CPU |
| Same load with the three foreign keys dropped first, then re-added in the same transaction (experiment, not adopted) | 15.6 s load + 1.3 s to re-add and validate = 16.9 s |

The full seed meets the 4-minute target, so the loader keeps its foreign keys during the load. Most of the 93 seconds is PostgreSQL's per-row foreign-key check on 6.5 million rows. Re-adding a foreign key afterwards validates every row in one set-based join instead.

## Consequences

- **The full seed takes about 1.5 minutes.** Dropping and re-adding the foreign keys inside the same transaction would cut that to about 17 seconds. The schema would stay unchanged for every other session, because the transaction holds exclusive locks from the `TRUNCATE` anyway. The cost is a loader that alters constraints. If it is ever adopted, the definitions should be read from `pg_constraint` so they cannot drift from the migrations.
- **The golden checksum ties the tests to Python's `random` implementation.** Python is pinned to 3.12. An interpreter upgrade that changes a sampling method fails the test, so the change is noticed and the value updated deliberately.
- **The data looks current only on the day it is seeded.** Re-seeding moves the history forward, and `data_version` invalidates caches.
- **`flask seed` replaces all sales data.** It is meant for development, CI and the demo stack, not for a database holding real orders.
- **Weekday and seasonal effects use UTC days.** Customers in different time zones all shop on UTC days, which is a simplification the analytics do not depend on.
