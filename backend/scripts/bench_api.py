"""Measure API latency: N authenticated requests, then p50, p95 and p99.

Logs in (as the demo account unless told otherwise), sends warm-up requests,
then sends N timed requests one after another over one keep-alive
connection. Each latency is the full round trip as a client sees it:
routing, token check, queries, serialization and the network hop.

Requests are sequential on purpose: the numbers describe how long one
request takes, not how many a server can take at once.

Cached endpoints report ``X-Cache``; the script counts the values it saw.
With ``--invalidate-cache`` it bumps ``data_version`` in Redis before each
request (outside the timing), so every request is a cache miss, which is
how uncached latency is measured. The bump also invalidates every other
cached response, so only use it against a development stack.

Usage, from ``backend/`` with the API running (for example under gunicorn)::

    uv run python -m scripts.bench_api --path "/api/orders" -n 1000
    uv run python -m scripts.bench_api --path "/api/orders?limit=25" --follow-cursor
    uv run python -m scripts.bench_api --path "/api/orders/{order_id}" --max-order-id 2000000
    uv run python -m scripts.bench_api --path "/api/analytics/summary" -n 100 --invalidate-cache
"""

import argparse
import json
import random
import statistics
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import quote, urlsplit

from redis import Redis

from app.config import get_settings
from app.services.cache import DATA_VERSION_KEY
from app.services.seeding import DEMO_EMAIL, DEMO_PASSWORD

ORDER_ID_PLACEHOLDER = "{order_id}"

CACHE_HEADER = "X-Cache"


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    body: bytes
    cache: str | None = None
    """The X-Cache header, if the endpoint sent one."""


Send = Callable[[str], Reply]
"""Send a GET for a path and return the reply."""


@dataclass(slots=True)
class Run:
    latencies_ms: list[float] = field(default_factory=list)
    cache: Counter[str] = field(default_factory=Counter)
    """How many replies carried each X-Cache value."""


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
    before_each: Callable[[], object] | None = None,
) -> Run:
    """Send ``count`` requests built from ``template``; return their latencies in milliseconds.

    ``{order_id}`` in the template is replaced by ``pick_order_id()`` on
    every request. With ``follow_cursor``, each request continues from the
    previous response's ``next_cursor``, restarting at the first page after
    the last, so the run reads ever deeper pages. ``before_each`` runs
    before every request, outside the timing.
    """
    if (ORDER_ID_PLACEHOLDER in template) != (pick_order_id is not None):
        raise ValueError("Give pick_order_id exactly when the template contains {order_id}")
    result = Run()
    cursor: str | None = None
    for _ in range(count):
        path = template
        if pick_order_id is not None:
            path = path.replace(ORDER_ID_PLACEHOLDER, str(pick_order_id()))
        if cursor is not None:
            path = with_cursor(path, cursor)
        if before_each is not None:
            before_each()
        started = time.perf_counter()
        reply = send(path)
        result.latencies_ms.append((time.perf_counter() - started) * 1000)
        if reply.status != 200:
            raise SystemExit(f"GET {path} answered {reply.status}: {reply.body[:300]!r}")
        if reply.cache is not None:
            result.cache[reply.cache] += 1
        if follow_cursor:
            cursor = json.loads(reply.body)["next_cursor"]
    return result


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

    def get(self, path: str) -> Reply:
        self._connection.request("GET", path, headers=self._headers)
        response = self._connection.getresponse()
        return Reply(response.status, response.read(), response.getheader(CACHE_HEADER))

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
    parser.add_argument(
        "--invalidate-cache",
        action="store_true",
        help="bump data_version in Redis (REDIS_URL) before every request, so each one misses",
    )
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
    redis = Redis.from_url(str(get_settings().redis_url)) if args.invalidate_cache else None

    def invalidate() -> None:
        if redis is not None:
            redis.incr(DATA_VERSION_KEY)

    def timed(count: int) -> Run:
        return run(
            client.get,
            args.path,
            count,
            follow_cursor=args.follow_cursor,
            pick_order_id=pick_order_id,
            before_each=invalidate,
        )

    try:
        client.log_in(args.email, args.password)
        timed(args.warmup)
        result = timed(args.requests)
    finally:
        client.close()
        if redis is not None:
            redis.close()
    stats = percentiles(result.latencies_ms)
    print(
        f"GET {args.path}: {args.requests} requests after {args.warmup} warm-up; "
        f"p50 {stats.p50:.2f} ms, p95 {stats.p95:.2f} ms, p99 {stats.p99:.2f} ms, "
        f"max {stats.max:.2f} ms, mean {stats.mean:.2f} ms" + format_cache(result.cache)
    )


def format_cache(cache: Counter[str]) -> str:
    """``; X-Cache MISS 100`` for the values seen, or nothing for an uncached endpoint."""
    if not cache:
        return ""
    counts = ", ".join(f"{status} {count}" for status, count in sorted(cache.items()))
    return f"; {CACHE_HEADER} {counts}"


if __name__ == "__main__":
    main()
