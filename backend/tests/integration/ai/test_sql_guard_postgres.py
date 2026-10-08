"""The SQL the guard regenerates is valid PostgreSQL that the read-only role can run.

sqlglot rewrites what it parses (generate_series becomes GENERATE_SERIES with
casts, for example). These tests run every accepted query of the unit tests
on the real database, so a rewrite PostgreSQL rejects fails here.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, scoped_session

from app.ai.sql_guard import guard_sql
from tests.unit.test_sql_guard import ACCEPTED_SQL, MAX_ROWS


@pytest.mark.parametrize("sql", ACCEPTED_SQL)
def test_guarded_sql_runs_on_postgresql_as_the_readonly_role(
    db_session: scoped_session[Session], sql: str
) -> None:
    guarded = guard_sql(sql, max_rows=MAX_ROWS)

    with db_session.begin_nested():
        db_session.execute(text("SET LOCAL ROLE datapilot_readonly"))
        db_session.execute(text("SET LOCAL search_path = analytics"))
        # Through psycopg without parameters, as the executor runs it: no
        # placeholder parsing, so "%" in LIKE patterns stays literal.
        driver = db_session.connection().connection.driver_connection
        assert driver is not None
        driver.execute(guarded.sql).fetchall()
