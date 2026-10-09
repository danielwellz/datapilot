"""Measure every API latency the README reports, in one run.

Logs in once (login is rate limited, so one process per scenario would be
refused), reads the data's last day and highest order id from the API, then
runs each scenario with ``scripts.bench_api``: warm-up requests, timed
sequential requests, percentiles. The result is printed as a Markdown table.

Uncached analytics rows bump ``data_version`` in Redis (``REDIS_URL``) before
each request. Every reply's ``X-Cache`` is checked against the row's kind,
so measuring a stack whose Redis is not ``REDIS_URL`` stops with an error
instead of reporting cached numbers as uncached. ``--skip-uncached`` leaves
those rows out, for example against the demo stack, whose Redis is not
published on the host.

Usage, from ``backend/`` with the API running on the full dataset::

    uv run python -m scripts.bench_suite
    uv run python -m scripts.bench_suite --base-url http://localhost:8080 --skip-uncached
"""

import argparse
import json
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial

from redis import Redis

from app.config import get_settings
from app.services.cache import DATA_VERSION_KEY
from app.services.seeding import DEMO_EMAIL, DEMO_PASSWORD
from scripts.bench_api import (
    ORDER_ID_PLACEHOLDER,
    ApiClient,
    Percentiles,
    Run,
    Send,
    percentiles,
    run,
)

# The customer with the most orders (about 1,400) in the full dataset with
# seed 42, whatever the end date: the slowest customer history.
BUSIEST_CUSTOMER_ID = 5880
COUNTRY_WINDOW_DAYS = 90

ANALYTICS_PATHS = (
    "/api/analytics/summary",
    "/api/analytics/summary?days=365",
    "/api/analytics/revenue-monthly",
    "/api/analytics/revenue-monthly?months=36",
    "/api/analytics/top-customers",
    "/api/analytics/products",
    "/api/analytics/cohorts",
    "/api/analytics/cohorts?months=24",
    "/api/meta",
)


@dataclass(frozen=True, slots=True)
class DataFacts:
    """What the scenarios need to know about the loaded data."""

    last_order_date: date
    max_order_id: int


@dataclass(frozen=True, slots=True)
class Scenario:
    path: str
    requests: int
    warmup: int
    follow_cursor: bool = False
    cache: str | None = None
    """The X-Cache value every timed reply must carry; None for uncached endpoints."""

    @property
    def invalidates(self) -> bool:
        return self.cache == "MISS"


@dataclass(frozen=True, slots=True)
class Measurement:
    scenario: Scenario
    stats: Percentiles


def read_facts(send: Send) -> DataFacts:
    """The newest order's date and id; order ids grow with ``created_at``."""
    meta = json.loads(send("/api/meta").body)
    newest = json.loads(send("/api/orders?limit=1").body)["items"]
    if meta["last_order_date"] is None or not newest:
        raise SystemExit("The database holds no orders. Seed it first: make seed scale=full")
    return DataFacts(
        last_order_date=date.fromisoformat(meta["last_order_date"]),
        max_order_id=newest[0]["id"],
    )


def build_scenarios(facts: DataFacts, *, include_uncached: bool) -> list[Scenario]:
    """The rows of the README's performance table, in its order."""
    date_from = facts.last_order_date - timedelta(days=COUNTRY_WINDOW_DAYS)
    scenarios = [
        Scenario("/api/orders", requests=500, warmup=20),
        Scenario("/api/orders?limit=25", requests=500, warmup=20, follow_cursor=True),
        Scenario(f"/api/orders?country=DE&date_from={date_from}", requests=500, warmup=20),
        Scenario(f"/api/orders?customer_id={BUSIEST_CUSTOMER_ID}", requests=500, warmup=20),
        Scenario(f"/api/orders/{ORDER_ID_PLACEHOLDER}", requests=1000, warmup=50),
    ]
    for path in ANALYTICS_PATHS:
        if include_uncached:
            scenarios.append(Scenario(path, requests=50, warmup=3, cache="MISS"))
        scenarios.append(Scenario(path, requests=500, warmup=50, cache="HIT"))
    return scenarios


def check_cache(scenario: Scenario, result: Run) -> None:
    """Stop unless every timed reply carried the X-Cache value the row reports."""
    if scenario.cache is None:
        return
    if result.cache.get(scenario.cache, 0) != scenario.requests:
        seen = ", ".join(f"{status} {count}" for status, count in sorted(result.cache.items()))
        raise SystemExit(
            f"GET {scenario.path}: expected X-Cache {scenario.cache} on all "
            f"{scenario.requests} requests, saw {seen or 'none'}. For uncached rows, "
            "REDIS_URL must point at the API's Redis; otherwise pass --skip-uncached."
        )


def run_scenario(
    send: Send,
    scenario: Scenario,
    count: int,
    *,
    invalidate: Callable[[], object] | None,
    pick_order_id: Callable[[], int],
) -> Run:
    return run(
        send,
        scenario.path,
        count,
        follow_cursor=scenario.follow_cursor,
        pick_order_id=pick_order_id if ORDER_ID_PLACEHOLDER in scenario.path else None,
        before_each=invalidate if scenario.invalidates else None,
    )


def measure(
    send: Send,
    scenarios: Sequence[Scenario],
    *,
    invalidate: Callable[[], object] | None,
    pick_order_id: Callable[[], int],
    on_done: Callable[[Measurement], object] = lambda measurement: None,
) -> list[Measurement]:
    """Run each scenario's warm-up, then its timed requests, and check its cache kind.

    ``invalidate`` runs before every request of an uncached row, outside the
    timing; without it those rows fail the cache check.
    """
    measurements = []
    for scenario in scenarios:
        timed = partial(
            run_scenario, send, scenario, invalidate=invalidate, pick_order_id=pick_order_id
        )
        timed(scenario.warmup)
        result = timed(scenario.requests)
        check_cache(scenario, result)
        measurement = Measurement(scenario, percentiles(result.latencies_ms))
        on_done(measurement)
        measurements.append(measurement)
    return measurements


def format_row(measurement: Measurement) -> str:
    scenario, stats = measurement.scenario, measurement.stats
    path = scenario.path + (" (following next_cursor)" if scenario.follow_cursor else "")
    kind = {"MISS": "uncached", "HIT": "cached"}.get(scenario.cache or "", "")
    cells = [
        f"`{path}`",
        kind,
        str(scenario.requests),
        *(f"{value:.1f} ms" for value in (stats.p50, stats.p95, stats.p99, stats.max)),
    ]
    return "| " + " | ".join(cells) + " |"


TABLE_HEADER = (
    "| Request | Cache | Requests | p50 | p95 | p99 | max |\n"
    "| --- | --- | ---: | ---: | ---: | ---: | ---: |"
)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument(
        "--skip-uncached",
        action="store_true",
        help="leave out the uncached analytics rows, which need the API's Redis at REDIS_URL",
    )
    parser.add_argument("--seed", type=int, default=42, help="seed for the random order ids")
    parser.add_argument("--email", default=DEMO_EMAIL)
    parser.add_argument("--password", default=DEMO_PASSWORD)
    args = parser.parse_args(argv)

    client = ApiClient(args.base_url)
    redis = None if args.skip_uncached else Redis.from_url(str(get_settings().redis_url))
    started = time.perf_counter()
    try:
        client.log_in(args.email, args.password)
        facts = read_facts(client.get)
        scenarios = build_scenarios(facts, include_uncached=not args.skip_uncached)
        print(
            f"{args.base_url}: orders up to {facts.last_order_date}, highest order id "
            f"{facts.max_order_id:,}; {len(scenarios)} scenarios, sequential requests.\n"
        )
        print(TABLE_HEADER, flush=True)
        rng = random.Random(args.seed)  # noqa: S311 (reproducible sampling, not security)
        measure(
            client.get,
            scenarios,
            invalidate=partial(redis.incr, DATA_VERSION_KEY) if redis is not None else None,
            pick_order_id=partial(rng.randint, 1, facts.max_order_id),
            on_done=lambda measurement: print(format_row(measurement), flush=True),
        )
    finally:
        client.close()
        if redis is not None:
            redis.close()
    print(f"\nFinished in {time.perf_counter() - started:.0f} s.")


if __name__ == "__main__":
    main()
