"""The SQL the guard regenerates is valid PostgreSQL that the read-only role can run.

sqlglot rewrites what it parses (generate_series becomes GENERATE_SERIES with
casts, for example). These tests run every accepted query of the unit tests
on the real database, so a rewrite PostgreSQL rejects fails here.
"""

import pytest

from app.ai.sql_guard import guard_sql
from tests.integration.ai.conftest import RunAsReadonly
from tests.unit.test_sql_guard import ACCEPTED_SQL, MAX_ROWS


@pytest.mark.parametrize("sql", ACCEPTED_SQL)
def test_guarded_sql_runs_on_postgresql_as_the_readonly_role(
    run_as_readonly: RunAsReadonly, sql: str
) -> None:
    guarded = guard_sql(sql, max_rows=MAX_ROWS)

    run_as_readonly(guarded.sql)
