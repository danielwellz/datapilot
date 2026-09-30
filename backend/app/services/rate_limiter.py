"""Fixed-window rate limiting backed by Redis.

Each (limiter, key) pair gets one counter per time window. The first hit in a
window creates the counter with an expiry, later hits increment it, and a hit
beyond the limit is refused until the window ends.

Fixed windows are the simplest correct scheme: one key and two commands per
hit. The known trade-off is the boundary burst, where a client can spend its
whole allowance at the end of one window and again at the start of the next
(up to twice the limit within a short span). For login throttling and a
per-user AI quota that is acceptable; a sliding window would need a sorted
set per key or weighted counters.
"""

import hashlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from redis import Redis

_KEY_PREFIX = "ratelimit"


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    # Hits left in the current window after this one.
    remaining: int
    # Whole seconds until the window ends; 0 when the hit was allowed.
    retry_after_seconds: int


class FixedWindowRateLimiter:
    """Allow at most ``limit`` hits per key in each window of ``window_seconds``.

    ``name`` separates limiters that share Redis (for example "login" and
    "ai"), so equal keys in different limiters never share a counter.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        name: str,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must both be at least 1")
        self._redis = redis
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock

    def hit(self, key: str) -> RateLimitDecision:
        """Count one attempt for ``key`` and decide whether it may proceed."""
        now = self._clock()
        window = int(now // self.window_seconds)
        redis_key = f"{_KEY_PREFIX}:{self.name}:{_digest(key)}:{window}"

        # MULTI/EXEC: the counter never exists without its expiry, even if the
        # process dies between the two commands. NX keeps the first expiry, so
        # later hits do not push it back.
        pipeline = self._redis.pipeline(transaction=True)
        pipeline.incr(redis_key)
        pipeline.expire(redis_key, self.window_seconds, nx=True)
        count, _ = pipeline.execute()

        if count > self.limit:
            window_end = (window + 1) * self.window_seconds
            # Never 0: "retry after 0 seconds" would invite an immediate retry
            # that may still land in this window.
            return RateLimitDecision(
                allowed=False,
                remaining=0,
                retry_after_seconds=max(1, math.ceil(window_end - now)),
            )
        return RateLimitDecision(allowed=True, remaining=self.limit - count, retry_after_seconds=0)


def _digest(key: str) -> str:
    # Keys often contain emails and IP addresses; hashing keeps them out of
    # Redis key listings, monitoring output and memory dumps.
    return hashlib.sha256(key.encode()).hexdigest()
