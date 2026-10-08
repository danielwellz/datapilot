"""The read-only role on its own, logged in for real, with no SQL guard in front of it.

Ask your data validates model-written SQL before running it. These tests
assume that validation was bypassed entirely and show what the database
still refuses: the role is the last line of defense, so it must hold alone.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, scoped_session

from app.config import Settings

ANALYTICS_VIEWS = ("v_orders", "v_order_items", "v_customers", "v_products")


@pytest.fixture
def readonly(settings: Settings) -> Iterator[Connection]:
    """A real login as datapilot_readonly, so login-time role settings apply."""
    engine = create_engine(str(settings.readonly_database_url))
    try:
        with engine.connect() as connection:
            yield connection
    finally:
        engine.dispose()


def _sqlstate(connection: Connection, statement: str, *, read_write: bool = False) -> str | None:
    """Run ``statement`` and return the SQLSTATE it fails with (None if it succeeds).

    ``read_write`` opens a read-write transaction first. The role's
    default_transaction_read_only is only a default, which any session may
    override, so refusals that matter must hold without it.
    """
    try:
        with connection.begin():
            if read_write:
                connection.execute(text("SET TRANSACTION READ WRITE"))
            connection.execute(text(statement))
    except DBAPIError as error:
        return getattr(error.orig, "sqlstate", None)
    return None


INSUFFICIENT_PRIVILEGE = "42501"
UNDEFINED_TABLE = "42P01"
READ_ONLY_TRANSACTION = "25006"


def test_readonly_login_applies_the_role_settings(readonly: Connection) -> None:
    def show(setting: str) -> str:
        return str(readonly.execute(text(f"SHOW {setting}")).scalar_one())

    assert readonly.execute(text("SELECT current_user")).scalar_one() == "datapilot_readonly"
    assert show("default_transaction_read_only") == "on"
    assert show("statement_timeout") == "5s"
    assert show("search_path") == "analytics"


@pytest.mark.parametrize("view", ANALYTICS_VIEWS)
def test_readonly_role_can_read_every_analytics_view(readonly: Connection, view: str) -> None:
    assert _sqlstate(readonly, f"SELECT count(*) FROM {view}") is None  # noqa: S608


@pytest.mark.parametrize("table", ["users", "customers", "orders", "order_items", "products"])
def test_readonly_role_cannot_read_public_tables(readonly: Connection, table: str) -> None:
    assert _sqlstate(readonly, f"SELECT * FROM public.{table}") == INSUFFICIENT_PRIVILEGE  # noqa: S608


def test_unqualified_table_names_do_not_reach_the_public_schema(readonly: Connection) -> None:
    assert _sqlstate(readonly, "SELECT * FROM users") == UNDEFINED_TABLE


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO analytics.v_products (name, category, price) VALUES ('x', 'y', 1)",
        "UPDATE analytics.v_orders SET total = 0",
        "DELETE FROM analytics.v_orders",
        "INSERT INTO public.users (email, full_name, password_hash) VALUES ('a@b.c', 'a', 'b')",
        "UPDATE public.orders SET total = 0",
        "DELETE FROM public.users",
        "DROP VIEW analytics.v_orders",
        "DROP TABLE public.users",
        "TRUNCATE public.orders",
        "CREATE TABLE analytics.stolen (id int)",
        "CREATE TABLE public.stolen (id int)",
        "ALTER VIEW analytics.v_orders RENAME TO v_gone",
        "SET ROLE datapilot",
    ],
)
def test_readonly_role_cannot_write_even_in_a_read_write_transaction(
    readonly: Connection, statement: str
) -> None:
    assert _sqlstate(readonly, statement, read_write=True) == INSUFFICIENT_PRIVILEGE


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TEMP TABLE scratch (id int)",
        # PostgreSQL lets any role change its own session defaults and
        # password. Only the read-only transaction stops that here, which is
        # why the executor also sets every limit per transaction (ADR 0007).
        "ALTER ROLE datapilot_readonly SET statement_timeout = 0",
        "ALTER ROLE datapilot_readonly PASSWORD 'chosen-by-an-attacker'",
    ],
)
def test_readonly_role_transactions_are_read_only_by_default(
    readonly: Connection, statement: str
) -> None:
    assert _sqlstate(readonly, statement) == READ_ONLY_TRANSACTION


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_ls_dir('.')",
        "COPY (SELECT 1) TO '/tmp/datapilot-copy'",
        "COPY (SELECT 1) TO PROGRAM 'true'",
        "SELECT lo_import('/etc/passwd')",
    ],
)
def test_readonly_role_cannot_use_server_side_file_or_process_functions(
    readonly: Connection, statement: str
) -> None:
    assert _sqlstate(readonly, statement, read_write=True) == INSUFFICIENT_PRIVILEGE


def test_readonly_role_cannot_terminate_the_applications_connections(
    readonly: Connection, db_session: scoped_session[Session]
) -> None:
    application_pid: int = db_session.execute(text("SELECT pg_backend_pid()")).scalar_one()

    statement = f"SELECT pg_terminate_backend({int(application_pid)})"
    assert _sqlstate(readonly, statement, read_write=True) == INSUFFICIENT_PRIVILEGE
