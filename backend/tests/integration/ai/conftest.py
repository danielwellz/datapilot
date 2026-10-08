"""Running SQL as the read-only role inside the test's rolled-back transaction.

A real login as datapilot_readonly would not see the rows a test inserted,
because they are never committed. ``SET LOCAL ROLE`` on the test's own
connection gives the role's privileges while seeing those rows; the
savepoint undoes the role switch afterwards.
"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, scoped_session

RunAsReadonly = Callable[[str], list[tuple[Any, ...]]]


@pytest.fixture
def run_as_readonly(db_session: scoped_session[Session]) -> RunAsReadonly:
    def run(sql: str) -> list[tuple[Any, ...]]:
        with db_session.begin_nested():
            db_session.execute(text("SET LOCAL ROLE datapilot_readonly"))
            db_session.execute(text("SET LOCAL search_path = analytics"))
            db_session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            # Through psycopg without parameters, as the executor runs it:
            # no placeholder parsing, so "%" in LIKE patterns stays literal.
            driver = db_session.connection().connection.driver_connection
            assert driver is not None
            return [tuple(row) for row in driver.execute(sql, binary=True).fetchall()]

    return run
