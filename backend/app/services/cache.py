"""Cache-aside for computed responses, keyed by the version of the data.

A request looks its key up first; on a miss it computes the value, stores it
with a TTL and returns it. Keys contain the current ``data_version``, which
every seed bumps, so a new dataset is never answered from the old one: the
old entries are simply never read again and expire on their own.

Stampede protection: when a popular key expires, every concurrent request
would recompute the same expensive query at once. Only the request that wins
a short lock (``SET NX PX``) computes; the others poll for its result for a
bounded time, then compute themselves rather than wait any longer.

Redis is a performance aid here, not a source of truth, so the cache fails
open: if Redis is unreachable the value is computed and served uncached.
"""

import logging
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlencode

from redis import Redis, RedisError

# Bumped after every seed (app.services.seeding); part of every cache key.
DATA_VERSION_KEY = "data_version"

DEFAULT_TTL_SECONDS = 600
# Longer than the slowest query it protects, so the lock does not expire
# while its holder is still computing and let a second computation start.
DEFAULT_LOCK_TTL_MS = 5_000
DEFAULT_WAIT_SECONDS = 3.0
DEFAULT_POLL_SECONDS = 0.025

_KEY_PREFIX = "cache"
_LOCK_PREFIX = "lock"

# Deletes the lock only if it still holds our token. A plain DEL could remove
# a lock that expired during a slow computation and was then taken by
# another request. One script, so the check and the delete are atomic.
_RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""

logger = logging.getLogger(__name__)

CacheParams = Mapping[str, str | int | None]
"""Normalized request parameters; ``None`` means "not given" and is left out of the key."""


class CacheStatus(StrEnum):
    """How a value was obtained, reported to clients in the ``X-Cache`` header."""

    HIT = "HIT"
    MISS = "MISS"
    # Redis failed, so the value was computed without the cache.
    BYPASS = "BYPASS"


@dataclass(frozen=True, slots=True)
class CacheResult:
    value: str
    status: CacheStatus


class ResponseCache:
    """Cache-aside over Redis for string values, such as serialized JSON bodies."""

    def __init__(
        self,
        redis: Redis,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        lock_ttl_ms: int = DEFAULT_LOCK_TTL_MS,
        wait_seconds: float = DEFAULT_WAIT_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds
        self._lock_ttl_ms = lock_ttl_ms
        self._wait_seconds = wait_seconds
        self._poll_seconds = poll_seconds
        self._clock = clock
        self._sleep = sleep
        self._release_lock = redis.register_script(_RELEASE_LOCK_SCRIPT)

    def get_or_compute(
        self, name: str, params: CacheParams, compute: Callable[[], str]
    ) -> CacheResult:
        """Return the cached value for ``name`` and ``params``, computing it on a miss.

        ``compute`` runs at most once per call. Its exceptions propagate and
        nothing is stored, so failures are never cached.
        """
        try:
            key = self.key(name, params)
            cached = _text(self._redis.get(key))
            if cached is not None:
                return CacheResult(cached, CacheStatus.HIT)
            token = self._acquire_lock(key)
            if token is None:
                cached = self._wait_for_value(key)
                if cached is not None:
                    return CacheResult(cached, CacheStatus.HIT)
        except RedisError:
            logger.warning("cache unavailable; computing %s uncached", name, exc_info=True)
            return CacheResult(compute(), CacheStatus.BYPASS)

        try:
            value = compute()
            stored = self._store(key, value)
        finally:
            if token is not None:
                self._unlock(key, token)
        return CacheResult(value, CacheStatus.MISS if stored else CacheStatus.BYPASS)

    def key(self, name: str, params: CacheParams) -> str:
        """The Redis key for ``name`` and ``params`` under the current data version.

        Parameters are sorted and URL-encoded, so their order never matters
        and a value containing ``&`` or ``=`` cannot be confused with a
        separator.
        """
        version = _text(self._redis.get(DATA_VERSION_KEY)) or "0"
        query = urlencode(sorted((k, str(v)) for k, v in params.items() if v is not None))
        return f"{_KEY_PREFIX}:{name}:v{version}:{query}"

    def _acquire_lock(self, key: str) -> str | None:
        """Take the computation lock for ``key``; return its token, or None if it is held."""
        token = secrets.token_hex(16)
        acquired = self._redis.set(_lock_key(key), token, nx=True, px=self._lock_ttl_ms)
        return token if acquired else None

    def _wait_for_value(self, key: str) -> str | None:
        """Poll until the lock holder stores the value, it gives up, or the wait ends."""
        deadline = self._clock() + self._wait_seconds
        while self._clock() < deadline:
            self._sleep(self._poll_seconds)
            value, lock = self._redis.mget(key, _lock_key(key))
            if value is not None:
                return _text(value)
            if lock is None:
                # The holder finished without storing a value (its computation
                # failed); waiting longer cannot help.
                return None
        return None

    def _store(self, key: str, value: str) -> bool:
        try:
            self._redis.set(key, value, ex=self._ttl_seconds)
        except RedisError:
            logger.warning("could not store %s in the cache", key, exc_info=True)
            return False
        return True

    def _unlock(self, key: str, token: str) -> None:
        try:
            self._release_lock(keys=[_lock_key(key)], args=[token])
        except RedisError:
            # The lock expires on its own; waiters stop at their deadline.
            logger.warning("could not release the cache lock for %s", key, exc_info=True)


def _lock_key(key: str) -> str:
    return f"{_LOCK_PREFIX}:{key}"


def _text(value: bytes | str | None) -> str | None:
    # The app's client decodes responses; a client that does not still works.
    return value.decode() if isinstance(value, bytes) else value
