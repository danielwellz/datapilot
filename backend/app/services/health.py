"""Readiness checks for the services the API cannot work without."""

import logging
from dataclasses import dataclass
from typing import Literal

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

CheckStatus = Literal["ok", "error"]


@dataclass(frozen=True)
class ReadinessReport:
    checks: dict[str, CheckStatus]

    @property
    def ready(self) -> bool:
        return all(status == "ok" for status in self.checks.values())


def check_readiness(engine: Engine, redis: Redis) -> ReadinessReport:
    """Check that PostgreSQL and Redis both answer.

    The database is checked on a connection taken from the pool, not through
    the request's session, so the probe reflects what the next request gets.
    """
    return ReadinessReport(
        checks={"database": _check_database(engine), "redis": _check_redis(redis)}
    )


def _check_database(engine: Engine) -> CheckStatus:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("readiness check failed", extra={"check": "database"}, exc_info=True)
        return "error"
    return "ok"


def _check_redis(redis: Redis) -> CheckStatus:
    try:
        redis.ping()
    except RedisError:
        logger.warning("readiness check failed", extra={"check": "redis"}, exc_info=True)
        return "error"
    return "ok"
