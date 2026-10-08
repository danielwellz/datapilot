"""Real PostgreSQL and Redis for integration tests, isolated per test.

Database: the schema is rebuilt from the migrations once per session. Each
test then runs inside one outer transaction that is rolled back afterwards.
Sessions join it with ``join_transaction_mode="create_savepoint"``, so code
under test can ``commit()`` and ``rollback()`` normally: those only release
or roll back savepoints, and nothing ever reaches the database for good.

Redis: tests use their own database index, flushed before and after each test.
"""

from collections.abc import Iterator

import flask_migrate
import pytest
from flask import Flask
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from app.config import Settings
from app.extensions import db, get_redis
from tests.factories import create_user
from tests.tokens import access_token_for, bearer


@pytest.fixture(scope="session")
def _migrated_database(app: Flask, settings: Settings) -> None:
    database = settings.database_url.path
    if not (database and database.endswith("_test")):
        pytest.exit(f"Refusing to reset {database!r}: the test database name must end in _test.")
    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        flask_migrate.upgrade()


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
def auth_headers(app: Flask) -> dict[str, str]:
    """An Authorization header for a freshly created analyst."""
    return bearer(access_token_for(app, create_user()))
