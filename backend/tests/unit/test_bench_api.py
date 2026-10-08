import json
from collections.abc import Iterator

import pytest

from scripts.bench_api import percentiles, run, with_cursor


def test_percentiles_of_one_to_a_hundred() -> None:
    stats = percentiles([float(value) for value in range(1, 101)])

    assert stats.p50 == pytest.approx(50.5)
    assert stats.p95 == pytest.approx(95.05)
    assert stats.p99 == pytest.approx(99.01)
    assert stats.max == 100
    assert stats.mean == pytest.approx(50.5)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/orders", "/api/orders?cursor=a%2Bb.c"),
        ("/api/orders?limit=25", "/api/orders?limit=25&cursor=a%2Bb.c"),
    ],
)
def test_with_cursor_appends_an_encoded_cursor(path: str, expected: str) -> None:
    assert with_cursor(path, "a+b.c") == expected


def test_run_fills_in_a_new_order_id_for_every_request() -> None:
    sent: list[str] = []
    ids: Iterator[int] = iter([7, 3, 9])

    def send(path: str) -> tuple[int, bytes]:
        sent.append(path)
        return 200, b"{}"

    latencies = run(send, "/api/orders/{order_id}", 3, pick_order_id=lambda: next(ids))

    assert sent == ["/api/orders/7", "/api/orders/3", "/api/orders/9"]
    assert len(latencies) == 3
    assert all(latency >= 0 for latency in latencies)


def test_run_follows_next_cursor_and_restarts_after_the_last_page() -> None:
    sent: list[str] = []
    cursors = iter(["c1", "c2", None, "c1"])

    def send(path: str) -> tuple[int, bytes]:
        sent.append(path)
        return 200, json.dumps({"items": [], "next_cursor": next(cursors)}).encode()

    run(send, "/api/orders?limit=25", 4, follow_cursor=True)

    assert sent == [
        "/api/orders?limit=25",
        "/api/orders?limit=25&cursor=c1",
        "/api/orders?limit=25&cursor=c2",
        "/api/orders?limit=25",
    ]


def test_run_stops_at_the_first_failed_request() -> None:
    def send(path: str) -> tuple[int, bytes]:
        return 404, b'{"error": {"code": "not_found"}}'

    with pytest.raises(SystemExit, match="answered 404"):
        run(send, "/api/orders/{order_id}", 5, pick_order_id=lambda: 1)


@pytest.mark.parametrize(
    ("template", "has_picker"), [("/api/orders/{order_id}", False), ("/api/orders", True)]
)
def test_run_requires_an_id_picker_exactly_for_id_templates(
    template: str, has_picker: bool
) -> None:
    with pytest.raises(ValueError, match="pick_order_id"):
        run(
            lambda path: (200, b"{}"),
            template,
            1,
            pick_order_id=(lambda: 1) if has_picker else None,
        )
