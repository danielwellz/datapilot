"""Real PostgreSQL and Redis for integration tests, isolated per test.

Database: the schema is rebuilt from the migrations once per session. Each
test then runs inside one outer transaction that is rolled back afterwards.
Sessions join it with ``join_transaction_mode="create_savepoint"``, so code
under test can ``commit()`` and ``rollback()`` normally: those only release
or roll back savepoints, and nothing ever reaches the database for good.

Redis: tests use their own database index, flushed before and after each test.
"""

import importlib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from functools import partial
from typing import Any

import flask_migrate
import pytest
from flask import Flask
from redis import Redis
from sqlalchemy import Connection, event, text
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from app.api import rate_limits
from app.config import Settings
from app.extensions import db, get_redis
from app.services.rate_limiter import FixedWindowRateLimiter
from tests.factories import create_user
from tests.tokens import access_token_for, bearer

QueryCounter = Callable[[], AbstractContextManager[list[str]]]

# The harness turns each commit into savepoint statements, which production
# never runs; they are not queries the code under test chose to make.
_HARNESS_STATEMENTS = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")

# Midnight UTC starts both a minute and an hour, so every limiter window in a
# test opens exactly here and Retry-After is always one whole window.
PINNED_NOW = datetime(2026, 1, 1, tzinfo=UTC).timestamp()


@pytest.fixture(scope="session")
def _migrated_database(app: Flask, settings: Settings) -> None:
    database = settings.database_url.path
    if not (database and database.endswith("_test")):
        pytest.exit(f"Refusing to reset {database!r}: the test database name must end in _test.")
    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS analytics CASCADE"))
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        flask_migrate.upgrade()
        # CI and fresh clusters have no password for the read-only role yet.
        result = app.test_cli_runner().invoke(args=["db-roles"])
        if result.exit_code != 0:
            pytest.exit(f"Could not set the read-only role's password: {result.output}")


@pytest.fixture(autouse=True)
def db_session(
    _migrated_database: None, app: Flask, monkeypatch: pytest.MonkeyPatch
) -> Iterator[scoped_session[Session]]:
    """Bind every session used during the test to one connection that is rolled back."""
    with app.app_context():
        connection = db.engine.connect()
    transaction = connection.begin()
    # Flask-SQLAlchemy's own session always picks the app's engine, ignoring
    # any bind given here, so a plain SQLAlchemy session stands in for it.
    session = scoped_session(
        sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    )
    monkeypatch.setattr(db, "session", session)
    try:
        yield session
    finally:
        session.remove()
        transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def redis_client(app: Flask, settings: Settings) -> Iterator[Redis]:
    if settings.redis_url.path in (None, "", "/", "/0"):
        pytest.exit("Refusing to flush Redis database 0: point TEST_REDIS_URL at another index.")
    with app.app_context():
        client = get_redis()
    client.flushdb()
    yield client
    client.flushdb()


@pytest.fixture
def pinned_rate_limit_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze the clock of the limiters the endpoints build at ``PINNED_NOW``.

    Limiter windows follow the wall clock, so a test whose hits straddle a
    window boundary sees its counter reset and never gets the expected 429.
    The endpoints build their limiters themselves, so the class they call is
    swapped for one with the clock already bound.
    """
    pinned = partial(FixedWindowRateLimiter, clock=lambda: PINNED_NOW)
    monkeypatch.setattr(rate_limits, "FixedWindowRateLimiter", pinned)
    # By module object: the name app.api.ai is the blueprint that package exports.
    monkeypatch.setattr(importlib.import_module("app.api.ai"), "FixedWindowRateLimiter", pinned)


@pytest.fixture
def auth_headers(app: Flask) -> dict[str, str]:
    """An Authorization header for a freshly created analyst."""
    return bearer(access_token_for(app, create_user()))


@pytest.fixture
def count_queries(db_session: scoped_session[Session]) -> QueryCounter:
    """Record the SQL run inside ``with count_queries() as statements:``.

    Used to prove an endpoint runs a fixed number of queries whatever the
    size of its result, which is how an N+1 query shows itself.
    """
    connection = db_session.get_bind()

    @contextmanager
    def counter() -> Iterator[list[str]]:
        statements: list[str] = []

        def record(
            _conn: Connection,
            _cursor: Any,
            statement: str,
            _parameters: Any,
            _context: Any,
            _executemany: bool,
        ) -> None:
            if not statement.startswith(_HARNESS_STATEMENTS):
                statements.append(statement)

        event.listen(connection, "before_cursor_execute", record)
        try:
            yield statements
        finally:
            event.remove(connection, "before_cursor_execute", record)

    return counter
