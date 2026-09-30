import pytest
from redis import Redis

from app.services.rate_limiter import FixedWindowRateLimiter, RateLimitDecision

# The start of a 60-second window, so offsets below read as "seconds into it".
WINDOW_START = 1_700_000_040.0


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(WINDOW_START)


def make_limiter(
    redis_client: Redis, clock: FakeClock, *, name: str = "test", limit: int = 3
) -> FixedWindowRateLimiter:
    return FixedWindowRateLimiter(
        redis_client, name=name, limit=limit, window_seconds=60, clock=clock
    )


def test_allows_hits_up_to_the_limit_and_counts_down_remaining(
    redis_client: Redis, clock: FakeClock
) -> None:
    limiter = make_limiter(redis_client, clock)

    decisions = [limiter.hit("ana") for _ in range(3)]

    assert decisions == [
        RateLimitDecision(allowed=True, remaining=2, retry_after_seconds=0),
        RateLimitDecision(allowed=True, remaining=1, retry_after_seconds=0),
        RateLimitDecision(allowed=True, remaining=0, retry_after_seconds=0),
    ]


def test_refuses_the_hit_after_the_limit_until_the_window_ends(
    redis_client: Redis, clock: FakeClock
) -> None:
    limiter = make_limiter(redis_client, clock)
    for _ in range(3):
        limiter.hit("ana")

    clock.now = WINDOW_START + 20.5
    decision = limiter.hit("ana")

    assert decision == RateLimitDecision(allowed=False, remaining=0, retry_after_seconds=40)


def test_retry_after_is_at_least_one_second_at_the_end_of_a_window(
    redis_client: Redis, clock: FakeClock
) -> None:
    limiter = make_limiter(redis_client, clock, limit=1)
    limiter.hit("ana")

    clock.now = WINDOW_START + 59.9
    decision = limiter.hit("ana")

    assert decision.allowed is False
    assert decision.retry_after_seconds == 1


def test_a_new_window_starts_a_fresh_count(redis_client: Redis, clock: FakeClock) -> None:
    limiter = make_limiter(redis_client, clock, limit=1)
    limiter.hit("ana")
    assert limiter.hit("ana").allowed is False

    clock.now = WINDOW_START + 60
    decision = limiter.hit("ana")

    assert decision == RateLimitDecision(allowed=True, remaining=0, retry_after_seconds=0)


def test_keys_are_counted_independently(redis_client: Redis, clock: FakeClock) -> None:
    limiter = make_limiter(redis_client, clock, limit=1)
    limiter.hit("ana")

    assert limiter.hit("ana").allowed is False
    assert limiter.hit("bruno").allowed is True


def test_limiters_with_different_names_do_not_share_counters(
    redis_client: Redis, clock: FakeClock
) -> None:
    login = make_limiter(redis_client, clock, name="login", limit=1)
    ai = make_limiter(redis_client, clock, name="ai", limit=1)
    login.hit("user-1")

    assert login.hit("user-1").allowed is False
    assert ai.hit("user-1").allowed is True


def test_counter_expires_after_one_window(redis_client: Redis, clock: FakeClock) -> None:
    limiter = make_limiter(redis_client, clock)
    limiter.hit("ana")
    limiter.hit("ana")

    (key,) = redis_client.keys("ratelimit:*")
    assert 0 < redis_client.ttl(key) <= 60


def test_raw_key_is_not_stored_in_redis(redis_client: Redis, clock: FakeClock) -> None:
    limiter = make_limiter(redis_client, clock)

    limiter.hit("203.0.113.9|ana@datapilot.dev")

    (key,) = redis_client.keys("*")
    assert isinstance(key, str)
    assert key.startswith("ratelimit:test:")
    assert "ana" not in key
    assert "203.0.113.9" not in key


@pytest.mark.parametrize(("limit", "window_seconds"), [(0, 60), (5, 0)])
def test_rejects_a_limit_or_window_below_one(
    redis_client: Redis, limit: int, window_seconds: int
) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        FixedWindowRateLimiter(
            redis_client, name="test", limit=limit, window_seconds=window_seconds
        )
