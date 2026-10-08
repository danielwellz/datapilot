"""Measure API latency: N authenticated requests, then p50, p95 and p99.

Logs in (as the demo account unless told otherwise), sends warm-up requests,
then sends N timed requests one after another over one keep-alive
connection. Each latency is the full round trip as a client sees it:
routing, token check, queries, serialization and the network hop.

Requests are sequential on purpose: the numbers describe how long one
request takes, not how many a server can take at once.

Usage, from ``backend/`` with the API running (for example under gunicorn)::

    uv run python -m scripts.bench_api --path "/api/orders" -n 1000
    uv run python -m scripts.bench_api --path "/api/orders?limit=25" --follow-cursor
    uv run python -m scripts.bench_api --path "/api/orders/{order_id}" --max-order-id 2000000
"""

import argparse
import json
import random
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import quote, urlsplit

from app.services.seeding import DEMO_EMAIL, DEMO_PASSWORD

ORDER_ID_PLACEHOLDER = "{order_id}"

Send = Callable[[str], tuple[int, bytes]]
"""Send a GET for a path; return the status and body."""


@dataclass(frozen=True, slots=True)
class Percentiles:
    p50: float
    p95: float
    p99: float
    max: float
    mean: float


def percentiles(latencies_ms: Sequence[float]) -> Percentiles:
    # "inclusive" treats the samples as the whole population, so p99 of 100
    # samples lies between the two slowest instead of beyond the slowest.
    cuts = statistics.quantiles(latencies_ms, n=100, method="inclusive")
    return Percentiles(
        p50=cuts[49],
        p95=cuts[94],
        p99=cuts[98],
        max=max(latencies_ms),
        mean=statistics.fmean(latencies_ms),
    )


def with_cursor(path: str, cursor: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}cursor={quote(cursor, safe='')}"


def run(
    send: Send,
    template: str,
    count: int,
    *,
    follow_cursor: bool = False,
    pick_order_id: Callable[[], int] | None = None,
) -> list[float]:
    """Send ``count`` requests built from ``template``; return each latency in milliseconds.

    ``{order_id}`` in the template is replaced by ``pick_order_id()`` on
    every request. With ``follow_cursor``, each request continues from the
    previous response's ``next_cursor``, restarting at the first page after
    the last, so the run reads ever deeper pages.
    """
    if (ORDER_ID_PLACEHOLDER in template) != (pick_order_id is not None):
        raise ValueError("Give pick_order_id exactly when the template contains {order_id}")
    latencies: list[float] = []
    cursor: str | None = None
    for _ in range(count):
        path = template
        if pick_order_id is not None:
            path = path.replace(ORDER_ID_PLACEHOLDER, str(pick_order_id()))
        if cursor is not None:
            path = with_cursor(path, cursor)
        started = time.perf_counter()
        status, body = send(path)
        latencies.append((time.perf_counter() - started) * 1000)
        if status != 200:
            raise SystemExit(f"GET {path} answered {status}: {body[:300]!r}")
        if follow_cursor:
            cursor = json.loads(body)["next_cursor"]
    return latencies


class ApiClient:
    """One persistent HTTP connection that carries a bearer token."""

    def __init__(self, base_url: str) -> None:
        parts = urlsplit(base_url)
        if parts.hostname is None:
            raise SystemExit(f"Not a URL: {base_url!r}")
        connection_class = HTTPSConnection if parts.scheme == "https" else HTTPConnection
        self._connection = connection_class(parts.hostname, parts.port, timeout=30)
        self._headers: dict[str, str] = {}

    def log_in(self, email: str, password: str) -> None:
        body = json.dumps({"email": email, "password": password})
        self._connection.request(
            "POST", "/api/auth/login", body, {"Content-Type": "application/json"}
        )
        response = self._connection.getresponse()
        payload = response.read()
        if response.status != 200:
            raise SystemExit(f"Login failed with {response.status}: {payload[:300]!r}")
        self._headers = {"Authorization": f"Bearer {json.loads(payload)['access_token']}"}

    def get(self, path: str) -> tuple[int, bytes]:
        self._connection.request("GET", path, headers=self._headers)
        response = self._connection.getresponse()
        return response.status, response.read()

    def close(self) -> None:
        self._connection.close()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument("--path", required=True, help="may contain {order_id}")
    parser.add_argument("-n", "--requests", type=int, default=1000, help="timed requests")
    parser.add_argument("--warmup", type=int, default=50, help="untimed requests first")
    parser.add_argument("--follow-cursor", action="store_true", help="walk ever deeper pages")
    parser.add_argument("--max-order-id", type=int, help="random ids for {order_id} up to this")
    parser.add_argument("--seed", type=int, default=42, help="seed for the random order ids")
    parser.add_argument("--email", default=DEMO_EMAIL)
    parser.add_argument("--password", default=DEMO_PASSWORD)
    args = parser.parse_args(argv)

    pick_order_id: Callable[[], int] | None = None
    if ORDER_ID_PLACEHOLDER in args.path:
        if args.max_order_id is None:
            parser.error("--path contains {order_id}, so --max-order-id is required")
        rng = random.Random(args.seed)  # noqa: S311 (reproducible sampling, not security)
        pick_order_id = partial(rng.randint, 1, args.max_order_id)

    client = ApiClient(args.base_url)

    def timed(count: int) -> list[float]:
        return run(
            client.get,
            args.path,
            count,
            follow_cursor=args.follow_cursor,
            pick_order_id=pick_order_id,
        )

    try:
        client.log_in(args.email, args.password)
        timed(args.warmup)
        stats = percentiles(timed(args.requests))
    finally:
        client.close()
    print(
        f"GET {args.path}: {args.requests} requests after {args.warmup} warm-up; "
        f"p50 {stats.p50:.2f} ms, p95 {stats.p95:.2f} ms, p99 {stats.p99:.2f} ms, "
        f"max {stats.max:.2f} ms, mean {stats.mean:.2f} ms"
    )


if __name__ == "__main__":
    main()
