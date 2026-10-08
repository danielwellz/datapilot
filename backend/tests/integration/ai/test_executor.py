"""The executor on a real login as the read-only role.

Most queries here would never pass the guard; they are built by hand on
purpose, to show what the executor and the role do on their own.
"""

from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy import Engine, create_engine

from app.ai.executor import (
    ColumnType,
    QueryFailedError,
    QueryRefusedError,
    QueryTimeoutError,
    ReadonlyExecutor,
)
from app.ai.sql_guard import GuardedSql
from app.config import Settings


@pytest.fixture
def readonly_engine(settings: Settings) -> Iterator[Engine]:
    engine = create_engine(str(settings.readonly_database_url))
    yield engine
    engine.dispose()


@pytest.fixture
def executor(readonly_engine: Engine) -> ReadonlyExecutor:
    return ReadonlyExecutor(readonly_engine, statement_timeout_ms=2000)


def _unguarded(sql: str, row_cap: int = 1000) -> GuardedSql:
    return GuardedSql(sql=sql, row_cap=row_cap)


def test_executor_returns_typed_columns_and_json_safe_rows(executor: ReadonlyExecutor) -> None:
    result = executor.run(
        _unguarded(
            "SELECT 12.50::numeric(10,2) AS revenue, 3 AS orders, 'US'::char(2) AS country,"
            " true AS paid, date '2026-10-01' AS month,"
            " timestamptz '2026-10-01 12:00:00+02' AS at, interval '1 day 2 hours' AS span"
        )
    )

    assert [(column.name, column.type) for column in result.columns] == [
        ("revenue", ColumnType.NUMBER),
        ("orders", ColumnType.NUMBER),
        ("country", ColumnType.STRING),
        ("paid", ColumnType.BOOLEAN),
        ("month", ColumnType.DATE),
        ("at", ColumnType.DATETIME),
        ("span", ColumnType.OTHER),
    ]
    assert result.rows == [
        ["12.50", 3, "US", True, "2026-10-01", "2026-10-01T10:00:00Z", "P1DT7200S"]
    ]
    assert (result.row_count, result.truncated) == (1, False)


def test_executor_runs_in_a_read_only_utc_transaction_with_its_own_timeout(
    readonly_engine: Engine,
) -> None:
    executor = ReadonlyExecutor(readonly_engine, statement_timeout_ms=1234)

    result = executor.run(
        _unguarded(
            "SELECT current_user, current_setting('transaction_read_only'),"
            " current_setting('statement_timeout'), current_setting('search_path'),"
            " current_setting('TimeZone')"
        )
    )

    assert result.rows == [["datapilot_readonly", "on", "1234ms", "analytics", "UTC"]]


def test_executor_reads_one_row_past_the_cap_to_flag_truncation(
    executor: ReadonlyExecutor,
) -> None:
    result = executor.run(_unguarded("SELECT n FROM generate_series(1, 5) AS n LIMIT 4", 3))

    assert result.rows == [[1], [2], [3]]
    assert result.truncated is True


def test_executor_does_not_read_placeholders_in_the_sql(executor: ReadonlyExecutor) -> None:
    result = executor.run(_unguarded("SELECT 'a%b' LIKE '%b' AS matches, '10:30' AS at"))

    assert result.rows == [[True, "10:30"]]


def test_executor_cancels_a_query_past_the_statement_timeout(readonly_engine: Engine) -> None:
    executor = ReadonlyExecutor(readonly_engine, statement_timeout_ms=50)

    with pytest.raises(QueryTimeoutError):
        executor.run(_unguarded("SELECT pg_sleep(2)"))


@pytest.mark.parametrize(
    ("sql", "sqlstate"),
    [
        ("SELECT * FROM public.users", "42501"),
        ("INSERT INTO v_products (name, category, price) VALUES ('x', 'y', 1)", "42501"),
        ("CREATE TEMP TABLE scratch (id int)", "25006"),
        # Runs, changes nothing (the transaction is rolled back), returns no rows.
        ("SET TRANSACTION READ WRITE", None),
    ],
)
def test_executor_reports_what_the_role_refuses(
    executor: ReadonlyExecutor, sql: str, sqlstate: str | None
) -> None:
    with pytest.raises(QueryRefusedError) as caught:
        executor.run(_unguarded(sql))

    assert caught.value.sqlstate == sqlstate


@pytest.mark.parametrize(
    ("sql", "sqlstate", "message"),
    [
        ("SELECT totl FROM v_orders", "42703", 'column "totl" does not exist'),
        ("SELECT 1 / 0", "22012", "division by zero"),
        ("SELECT 'abc'::int", "22P02", "invalid input syntax for type integer"),
        ("SELECT * FROM v_orderz", "42P01", 'relation "v_orderz" does not exist'),
        # Refused by the protocol itself, before either statement runs.
        ("SELECT 1; DELETE FROM v_orders", "42601", "cannot insert multiple commands"),
        (
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY 1) OVER ()",
            "0A000",
            "OVER is not supported",
        ),
    ],
)
def test_executor_reports_errors_the_model_can_fix(
    executor: ReadonlyExecutor, sql: str, sqlstate: str, message: str
) -> None:
    with pytest.raises(QueryFailedError) as caught:
        executor.run(_unguarded(sql))

    assert caught.value.sqlstate == sqlstate
    assert message in caught.value.message
    # PostgreSQL's position marker and query echo stay out of the message.
    assert "LINE 1" not in caught.value.message


def test_executor_includes_postgresqls_hint(executor: ReadonlyExecutor) -> None:
    with pytest.raises(QueryFailedError) as caught:
        executor.run(_unguarded("SELECT round(1.5::float8, 2)"))

    assert "(hint: No function matches" in caught.value.message


def test_executor_lets_server_errors_through_unchanged(executor: ReadonlyExecutor) -> None:
    # 57014 is the class of the timeout; any other operator-intervention error,
    # such as this one raised on purpose, is not the query's fault.
    sql = "DO $$ BEGIN RAISE EXCEPTION USING ERRCODE = '57P01'; END $$"

    with pytest.raises(psycopg.errors.AdminShutdown):
        executor.run(_unguarded(sql))
