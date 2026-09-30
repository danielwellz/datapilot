"""Rate-limit rules for endpoints, enforced with the Redis limiter."""

from dataclasses import dataclass

from app.errors import RateLimited
from app.extensions import get_redis
from app.services.rate_limiter import FixedWindowRateLimiter


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int
    message: str


def enforce_rate_limit(rule: RateLimitRule, key: str) -> None:
    """Count one hit of ``key`` against ``rule``; raise 429 once the rule's limit is spent."""
    limiter = FixedWindowRateLimiter(
        get_redis(), name=rule.name, limit=rule.limit, window_seconds=rule.window_seconds
    )
    decision = limiter.hit(key)
    if not decision.allowed:
        raise RateLimited(decision.retry_after_seconds, rule.message)
