"""Runs guarded SQL as the read-only role and turns the result into JSON-safe rows.

Only SQL that passed the guard reaches this module, but nothing here relies
on that. Each query runs on a connection that logged in as
``datapilot_readonly``, inside a transaction that is read-only, has its own
statement timeout and search path, and is always rolled back. The role sets
the same limits at login; they are set again per transaction because a
session can change its own defaults (ADR 0007).
"""

import base64
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.postgres import types as pg_types
from pydantic import JsonValue
from sqlalchemy import Connection, Engine

from app.ai.sql_guard import ALLOWED_SCHEMA, GuardedSql

# SQLSTATE classes that describe the server or the connection rather than
# the query (connection loss, resources, shutdown, system and internal
# errors). Rewriting the query cannot fix them, so they are not sent back to
# the model; every other error (an unknown column, a bad cast, division by
# zero, an unsupported construct) can be.
_INFRASTRUCTURE_SQLSTATE_CLASSES = ("08", "53", "57", "58", "XX")


class ColumnType(StrEnum):
    NUMBER = "number"
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    OTHER = "other"


_COLUMN_TYPES: dict[str, ColumnType] = {
    **dict.fromkeys(
        ("int2", "int4", "int8", "float4", "float8", "numeric", "oid"), ColumnType.NUMBER
    ),
    **dict.fromkeys(("text", "varchar", "bpchar", "name"), ColumnType.STRING),
    "bool": ColumnType.BOOLEAN,
    "date": ColumnType.DATE,
    **dict.fromkeys(("timestamp", "timestamptz"), ColumnType.DATETIME),
}


@dataclass(frozen=True, slots=True)
class ResultColumn:
    name: str
    # A hint for display and charts; the values themselves are JSON-safe.
    type: ColumnType


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: list[ResultColumn]
    rows: list[list[JsonValue]]
    truncated: bool

    @property
    def row_count(self) -> int:
        return len(self.rows)


class QueryTimeoutError(Exception):
    """The query ran past the statement timeout and was cancelled."""


class QueryFailedError(Exception):
    """PostgreSQL refused the query in a way the model may be able to fix."""

    def __init__(self, message: str, sqlstate: str | None) -> None:
        super().__init__(message)
        self.message = message
        self.sqlstate = sqlstate


class QueryRefusedError(Exception):
    """The read-only role refused the query: the guard let through something it should not have."""

    def __init__(self, message: str, sqlstate: str | None) -> None:
        super().__init__(message)
        self.message = message
        self.sqlstate = sqlstate


class ReadonlyExecutor:
    """Runs guarded queries on the engine that logs in as the read-only role."""

    def __init__(self, engine: Engine, *, statement_timeout_ms: int) -> None:
        self._engine = engine
        self._statement_timeout_ms = statement_timeout_ms

    def run(self, guarded: GuardedSql) -> QueryResult:
        with self._engine.connect() as connection:
            transaction = connection.begin()
            try:
                # Must come first in the transaction, before any query.
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                apply_query_limits(connection, self._statement_timeout_ms)
                return fetch_result(connection, guarded)
            finally:
                # Nothing a read-only query does is worth keeping.
                transaction.rollback()


def apply_query_limits(connection: Connection, statement_timeout_ms: int) -> None:
    """Set the per-transaction limits every model-written query runs under."""
    # An int, so formatting it into the statement is safe; SET takes no parameters.
    connection.exec_driver_sql(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
    connection.exec_driver_sql(f"SET LOCAL search_path = {ALLOWED_SCHEMA}")
    # Dates and months in answers are UTC calendar periods, whatever the server's zone.
    connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")


def fetch_result(connection: Connection, guarded: GuardedSql) -> QueryResult:
    """Run ``guarded`` on ``connection`` and read at most its row cap plus one rows."""
    # The engines are built on psycopg, so the driver connection is one.
    driver_connection = cast("psycopg.Connection[Any]", connection.connection.driver_connection)
    try:
        # No parameters, so psycopg sends the text as it is: "%" and ":" in
        # the SQL are never read as placeholders. Binary results make it use
        # the extended query protocol, which refuses more than one statement
        # per call: a second statement cannot ride along with the first.
        cursor = driver_connection.execute(guarded.sql, binary=True)
        if cursor.description is None:
            raise QueryRefusedError("Only queries that return rows may run.", None)
        description = cursor.description
        rows = cursor.fetchmany(guarded.row_cap + 1)
    except pg_errors.QueryCanceled as error:
        raise QueryTimeoutError(str(error)) from error
    except (pg_errors.InsufficientPrivilege, pg_errors.ReadOnlySqlTransaction) as error:
        raise QueryRefusedError(_error_message(error), error.sqlstate) from error
    except psycopg.DatabaseError as error:
        if (error.sqlstate or "XX")[:2] in _INFRASTRUCTURE_SQLSTATE_CLASSES:
            raise
        raise QueryFailedError(_error_message(error), error.sqlstate) from error

    columns = [ResultColumn(column.name, _column_type(column.type_code)) for column in description]
    return QueryResult(
        columns=columns,
        rows=[[to_json_value(value) for value in row] for row in rows[: guarded.row_cap]],
        truncated=len(rows) > guarded.row_cap,
    )


def _error_message(error: psycopg.Error) -> str:
    """PostgreSQL's message and hint, without the query position or internals."""
    message = error.diag.message_primary or str(error)
    return f"{message} (hint: {error.diag.message_hint})" if error.diag.message_hint else message


def _column_type(type_code: int) -> ColumnType:
    info = pg_types.get(type_code)
    return _COLUMN_TYPES.get(info.name, ColumnType.OTHER) if info else ColumnType.OTHER


def to_json_value(value: Any) -> JsonValue:
    """A database value as JSON, following the API's conventions.

    Decimals become strings so no precision is lost, instants become ISO 8601
    in UTC with a "Z", and anything without a JSON form becomes text.
    """
    match value:
        case None | bool() | int() | str():
            return value
        case float():
            return value if math.isfinite(value) else str(value)
        case Decimal():
            return str(value)
        case datetime() if value.tzinfo is not None:
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        case datetime() | date() | time():
            return value.isoformat()
        case timedelta():
            return _iso_duration(value)
        case UUID():
            return str(value)
        case bytes() | bytearray() | memoryview():
            return base64.b64encode(bytes(value)).decode("ascii")
        case dict():
            return {str(key): to_json_value(item) for key, item in value.items()}
        case list() | tuple():
            return [to_json_value(item) for item in value]
        case _:
            return str(value)


def _iso_duration(value: timedelta) -> str:
    sign = "-" if value < timedelta(0) else ""
    value = abs(value)
    seconds = value.seconds + value.microseconds / 1_000_000
    return f"{sign}P{value.days}DT{seconds:g}S"
