import json
from datetime import date

import pytest

from scripts.bench_api import Percentiles, Reply
from scripts.bench_suite import (
    TABLE_HEADER,
    DataFacts,
    Measurement,
    Scenario,
    build_scenarios,
    format_row,
    measure,
    read_facts,
)

FACTS = DataFacts(last_order_date=date(2026, 10, 7), max_order_id=2_000_000)


def json_reply(payload: object) -> Reply:
    return Reply(200, json.dumps(payload).encode())


def test_read_facts_takes_the_last_day_from_meta_and_the_newest_order_id() -> None:
    replies = {
        "/api/meta": json_reply({"last_order_date": "2026-10-07"}),
        "/api/orders?limit=1": json_reply({"items": [{"id": 2_000_000}], "next_cursor": "c"}),
    }

    assert read_facts(replies.__getitem__) == FACTS


def test_read_facts_stops_when_there_are_no_orders() -> None:
    replies = {
        "/api/meta": json_reply({"last_order_date": None}),
        "/api/orders?limit=1": json_reply({"items": [], "next_cursor": None}),
    }

    with pytest.raises(SystemExit, match="Seed it first"):
        read_facts(replies.__getitem__)


def test_build_scenarios_dates_the_country_filter_from_the_data() -> None:
    paths = [scenario.path for scenario in build_scenarios(FACTS, include_uncached=True)]

    assert "/api/orders?country=DE&date_from=2026-07-09" in paths


def test_build_scenarios_measures_each_analytics_path_uncached_and_cached() -> None:
    scenarios = build_scenarios(FACTS, include_uncached=True)
    summary = [s for s in scenarios if s.path == "/api/analytics/summary"]

    assert [(s.cache, s.requests, s.warmup) for s in summary] == [
        ("MISS", 50, 3),
        ("HIT", 500, 50),
    ]
    assert all(s.cache is None for s in scenarios if s.path.startswith("/api/orders"))


def test_build_scenarios_without_uncached_rows_never_invalidates() -> None:
    scenarios = build_scenarios(FACTS, include_uncached=False)

    assert not any(scenario.invalidates for scenario in scenarios)
    assert len(scenarios) == len(build_scenarios(FACTS, include_uncached=True)) - 9


def test_measure_invalidates_before_each_uncached_request_only() -> None:
    events: list[str] = []
    # Warm-up and timed requests: three misses for the uncached row, then a
    # miss that fills the cache and two hits for the cached row.
    statuses = iter(["MISS", "MISS", "MISS", "MISS", "HIT", "HIT"])

    def send(path: str) -> Reply:
        events.append(path)
        return Reply(200, b"{}", next(statuses))

    uncached = Scenario("/api/meta", requests=2, warmup=1, cache="MISS")
    cached = Scenario("/api/meta", requests=2, warmup=1, cache="HIT")

    measurements = measure(
        send,
        [uncached, cached],
        invalidate=lambda: events.append("bump"),
        pick_order_id=lambda: 1,
    )

    assert events == ["bump", "/api/meta"] * 3 + ["/api/meta"] * 3
    assert [measurement.scenario for measurement in measurements] == [uncached, cached]


def test_measure_picks_a_new_order_id_for_detail_requests() -> None:
    sent: list[str] = []
    ids = iter(range(1, 100))

    def send(path: str) -> Reply:
        sent.append(path)
        return Reply(200, b"{}")

    measure(
        send,
        [Scenario("/api/orders/{order_id}", requests=2, warmup=1)],
        invalidate=None,
        pick_order_id=lambda: next(ids),
    )

    assert sent == ["/api/orders/1", "/api/orders/2", "/api/orders/3"]


@pytest.mark.parametrize(
    ("expected", "replies"),
    [("MISS", ["MISS", "HIT"]), ("HIT", ["HIT", "MISS"]), ("HIT", [None, None])],
)
def test_measure_stops_when_a_timed_reply_has_the_wrong_cache_kind(
    expected: str, replies: list[str | None]
) -> None:
    statuses = iter(replies)

    def send(path: str) -> Reply:
        return Reply(200, b"{}", next(statuses))

    with pytest.raises(SystemExit, match=f"expected X-Cache {expected} on all 2 requests"):
        measure(
            send,
            [Scenario("/api/meta", requests=2, warmup=0, cache=expected)],
            invalidate=lambda: None,
            pick_order_id=lambda: 1,
        )


def test_measure_reports_each_row_as_soon_as_it_is_done() -> None:
    reported: list[str] = []

    measure(
        lambda path: Reply(200, b"{}"),
        [Scenario("/api/orders", 2, 0), Scenario("/api/orders?limit=25", 2, 0)],
        invalidate=None,
        pick_order_id=lambda: 1,
        on_done=lambda measurement: reported.append(measurement.scenario.path),
    )

    assert reported == ["/api/orders", "/api/orders?limit=25"]


def test_format_row_matches_the_table_header() -> None:
    stats = Percentiles(p50=7.54, p95=8.91, p99=10.66, max=52.0, mean=7.8)
    row = format_row(Measurement(Scenario("/api/orders?limit=25", 500, 20, True), stats))
    cached = format_row(Measurement(Scenario("/api/meta", 500, 50, cache="HIT"), stats))

    assert row == (
        "| `/api/orders?limit=25 (following next_cursor)` |  | 500 "
        "| 7.5 ms | 8.9 ms | 10.7 ms | 52.0 ms |"
    )
    assert cached.startswith("| `/api/meta` | cached | 500 |")
    assert row.count("|") == TABLE_HEADER.splitlines()[0].count("|")
