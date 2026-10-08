from collections.abc import Callable, Iterator

import pytest
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.services.cache import (
    DATA_VERSION_KEY,
    DEFAULT_TTL_SECONDS,
    CacheParams,
    CacheStatus,
    ResponseCache,
)
from tests.logs import LogCapture
from tests.settings import make_test_settings

NAME = "analytics:summary"
PARAMS: CacheParams = {"days": 30, "as_of": "2026-10-08"}


class FakeTime:
    """A clock and a sleep that advances it, with an optional hook run on each sleep."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps = 0
        self.on_sleep: Callable[[], None] = lambda: None

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.sleeps += 1
        self.on_sleep()


class Computation:
    """A compute callback that counts its calls."""

    def __init__(self, value: str = '{"revenue": "10.00"}') -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.value


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
def cache(redis_client: Redis, fake_time: FakeTime) -> ResponseCache:
    return ResponseCache(
        redis_client,
        wait_seconds=1.0,
        poll_seconds=0.1,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
    )


def lock_key(cache: ResponseCache) -> str:
    return f"lock:{cache.key(NAME, PARAMS)}"


def test_first_call_misses_and_computes_then_the_next_call_hits(cache: ResponseCache) -> None:
    compute = Computation()

    first = cache.get_or_compute(NAME, PARAMS, compute)
    second = cache.get_or_compute(NAME, PARAMS, compute)

    assert (first.status, first.value) == (CacheStatus.MISS, compute.value)
    assert (second.status, second.value) == (CacheStatus.HIT, compute.value)
    assert compute.calls == 1


def test_stored_value_expires_after_the_ttl(cache: ResponseCache, redis_client: Redis) -> None:
    cache.get_or_compute(NAME, PARAMS, Computation())

    ttl = redis_client.ttl(cache.key(NAME, PARAMS))

    assert DEFAULT_TTL_SECONDS - 5 < ttl <= DEFAULT_TTL_SECONDS


def test_key_ignores_parameter_order_and_parameters_not_given(cache: ResponseCache) -> None:
    assert cache.key(NAME, {"b": 2, "a": "x", "c": None}) == cache.key(NAME, {"a": "x", "b": 2})


def test_key_encodes_values_so_separators_inside_them_stay_unambiguous(
    cache: ResponseCache,
) -> None:
    joined = cache.key(NAME, {"category": "Home&limit=5"})
    separate = cache.key(NAME, {"category": "Home", "limit": 5})

    assert joined != separate
    assert joined == "cache:analytics:summary:v0:category=Home%26limit%3D5"


def test_different_parameters_or_names_get_their_own_entries(cache: ResponseCache) -> None:
    thirty, seven, other = Computation("30"), Computation("7"), Computation("other")

    assert cache.get_or_compute(NAME, {"days": 30}, thirty).value == "30"
    assert cache.get_or_compute(NAME, {"days": 7}, seven).value == "7"
    assert cache.get_or_compute("analytics:products", {"days": 30}, other).value == "other"
    assert (thirty.calls, seven.calls, other.calls) == (1, 1, 1)


def test_bumping_the_data_version_invalidates_every_entry(
    cache: ResponseCache, redis_client: Redis
) -> None:
    old, new = Computation("old"), Computation("new")
    cache.get_or_compute(NAME, PARAMS, old)

    redis_client.incr(DATA_VERSION_KEY)
    result = cache.get_or_compute(NAME, PARAMS, new)

    assert (result.status, result.value) == (CacheStatus.MISS, "new")
    assert cache.key(NAME, PARAMS).startswith("cache:analytics:summary:v1:")


def test_a_failed_computation_is_not_cached_and_releases_the_lock(
    cache: ResponseCache, redis_client: Redis
) -> None:
    def fail() -> str:
        raise RuntimeError("query failed")

    with pytest.raises(RuntimeError, match="query failed"):
        cache.get_or_compute(NAME, PARAMS, fail)

    assert redis_client.get(cache.key(NAME, PARAMS)) is None
    assert redis_client.get(lock_key(cache)) is None


def test_lock_is_released_after_a_successful_computation(
    cache: ResponseCache, redis_client: Redis
) -> None:
    held_during_compute: list[bool] = []

    def compute() -> str:
        held_during_compute.append(redis_client.exists(lock_key(cache)) == 1)
        return "value"

    cache.get_or_compute(NAME, PARAMS, compute)

    assert held_during_compute == [True]
    assert redis_client.get(lock_key(cache)) is None


def test_lock_expires_on_its_own_if_its_holder_never_releases_it(
    cache: ResponseCache, redis_client: Redis
) -> None:
    def compute() -> str:
        ttl_ms = redis_client.pttl(lock_key(cache))
        assert 0 < ttl_ms <= 5_000
        return "value"

    cache.get_or_compute(NAME, PARAMS, compute)


def test_waiter_returns_the_value_the_lock_holder_stores(
    cache: ResponseCache, redis_client: Redis, fake_time: FakeTime
) -> None:
    redis_client.set(lock_key(cache), "other-request")
    compute = Computation()

    def holder_finishes_on_second_poll() -> None:
        if fake_time.sleeps == 2:
            redis_client.set(cache.key(NAME, PARAMS), "computed by the holder")

    fake_time.on_sleep = holder_finishes_on_second_poll

    result = cache.get_or_compute(NAME, PARAMS, compute)

    assert (result.status, result.value) == (CacheStatus.HIT, "computed by the holder")
    assert compute.calls == 0


def test_waiter_computes_itself_when_the_holder_takes_longer_than_the_wait(
    cache: ResponseCache, redis_client: Redis, fake_time: FakeTime
) -> None:
    redis_client.set(lock_key(cache), "other-request")
    compute = Computation()

    result = cache.get_or_compute(NAME, PARAMS, compute)

    assert (result.status, result.value) == (CacheStatus.MISS, compute.value)
    assert compute.calls == 1
    # wait_seconds=1.0 polled every 0.1 s.
    assert fake_time.sleeps == pytest.approx(10, abs=1)
    assert redis_client.get(cache.key(NAME, PARAMS)) == compute.value
    # The waiter never held the lock, so it leaves the holder's lock alone.
    assert redis_client.get(lock_key(cache)) == "other-request"


def test_waiter_stops_waiting_when_the_holder_releases_the_lock_without_a_value(
    cache: ResponseCache, redis_client: Redis, fake_time: FakeTime
) -> None:
    redis_client.set(lock_key(cache), "other-request")

    def holder_gives_up() -> None:
        redis_client.delete(lock_key(cache))

    fake_time.on_sleep = holder_gives_up
    compute = Computation()

    result = cache.get_or_compute(NAME, PARAMS, compute)

    assert result.status == CacheStatus.MISS
    assert compute.calls == 1
    assert fake_time.sleeps == 1


def test_release_keeps_a_lock_that_another_request_took_over(
    cache: ResponseCache, redis_client: Redis
) -> None:
    def slow_compute() -> str:
        # Our lock expired during a slow computation and another request took it.
        redis_client.set(lock_key(cache), "newer-request")
        return "value"

    cache.get_or_compute(NAME, PARAMS, slow_compute)

    assert redis_client.get(lock_key(cache)) == "newer-request"


@pytest.fixture
def unreachable_redis() -> Iterator[Redis]:
    # Port 1 refuses connections at once, like a stopped Redis.
    client = Redis(host="localhost", port=1, socket_connect_timeout=0.5)
    yield client
    client.close()


def test_unreachable_redis_serves_the_computed_value_uncached_and_warns(
    unreachable_redis: Redis, captured_logs: LogCapture
) -> None:
    compute = Computation()

    result = ResponseCache(unreachable_redis).get_or_compute(NAME, PARAMS, compute)

    assert (result.status, result.value) == (CacheStatus.BYPASS, compute.value)
    assert compute.calls == 1
    [warning] = captured_logs.records("app.services.cache")
    assert warning["message"] == "cache unavailable; computing analytics:summary uncached"
    assert warning["level"] == "WARNING"
    assert "ConnectionError" in warning["exc_info"]


class FailingWrites(Redis):
    """A Redis client whose plain SET (without NX) and script calls fail."""

    def set(self, name, value, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not kwargs.get("nx"):
            raise RedisConnectionError("write failed")
        return super().set(name, value, *args, **kwargs)

    def evalsha(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RedisConnectionError("script failed")


@pytest.fixture
def failing_writes(redis_client: Redis) -> Iterator[Redis]:
    url = str(make_test_settings().redis_url)
    client = FailingWrites.from_url(url, decode_responses=True)
    yield client
    client.close()


def test_failing_to_store_or_unlock_still_serves_the_value_and_warns(
    failing_writes: Redis, redis_client: Redis, captured_logs: LogCapture
) -> None:
    cache = ResponseCache(failing_writes)

    result = cache.get_or_compute(NAME, PARAMS, Computation("value"))

    assert (result.status, result.value) == (CacheStatus.BYPASS, "value")
    messages = {record["message"] for record in captured_logs.records("app.services.cache")}
    key = cache.key(NAME, PARAMS)
    assert f"could not store {key} in the cache" in messages
    assert f"could not release the cache lock for {key}" in messages
    # The lock is left to expire on its own.
    assert 0 < redis_client.pttl(f"lock:{key}") <= 5_000


def test_values_from_a_client_without_response_decoding_are_text(redis_client: Redis) -> None:
    url = str(make_test_settings().redis_url)
    raw = Redis.from_url(url)
    try:
        cache = ResponseCache(raw)
        cache.get_or_compute(NAME, PARAMS, Computation("stored"))

        result = cache.get_or_compute(NAME, PARAMS, Computation("unused"))
    finally:
        raw.close()

    assert (result.status, result.value) == (CacheStatus.HIT, "stored")
