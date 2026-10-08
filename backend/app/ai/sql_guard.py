"""Decides whether model-written SQL may run, and rewrites it into the form that does.

The SQL comes from a language model, so it is untrusted input, however the
question was phrased and whichever model wrote it. The guard parses it with
sqlglot (PostgreSQL dialect) and accepts exactly one read-only query over the
curated ``analytics`` views:

- one statement, which is a SELECT (WITH and UNION/INTERSECT/EXCEPT allowed);
- nothing inside it that writes or locks (data-modifying CTEs, SELECT INTO,
  FOR UPDATE);
- every table is an allowed view, or a CTE visible where it is referenced;
- no other schema, and no function that can sleep, read files, signal
  backends, change settings or run SQL from a string.

What runs is not the model's text but the SQL regenerated from the checked
tree, with comments removed and a row limit applied, so the database
executes exactly what was checked. The guard is one layer of several: the
read-only role refuses all of the above on its own (ADR 0007).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.scope import Scope, traverse_scope

ALLOWED_SCHEMA = "analytics"
ALLOWED_VIEWS = frozenset({"v_orders", "v_order_items", "v_customers", "v_products"})
# Far above any sensible analytics query; also bounds the parser's work.
MAX_SQL_LENGTH = 10_000

_DIALECT = "postgres"
_CALL_NAME = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")

# Set-returning functions allowed in FROM: they only generate values.
_TABLE_FUNCTIONS = frozenset({"generate_series", "unnest"})

# Prefixes cover whole families: pg_sleep, pg_read_file, pg_ls_dir,
# pg_terminate_backend, pg_advisory_lock...; lo_import and lo_export;
# dblink and dblink_exec.
_FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink")
_FORBIDDEN_FUNCTIONS = frozenset(
    {
        # Read or change server settings.
        "set_config",
        "current_setting",
        # Run SQL passed as a string, which the guard never sees.
        "query_to_xml",
        "query_to_xmlschema",
        "query_to_xml_and_xmlschema",
        "cursor_to_xml",
        "cursor_to_xmlschema",
        "table_to_xml",
        "table_to_xmlschema",
        "table_to_xml_and_xmlschema",
        "schema_to_xml",
        "schema_to_xmlschema",
        "schema_to_xml_and_xmlschema",
        "database_to_xml",
        "database_to_xmlschema",
        "database_to_xml_and_xmlschema",
        "ts_stat",
        "ts_rewrite",
        # Change sequences.
        "nextval",
        "setval",
        "currval",
        "lastval",
        # Reveals the server version, which helps an attacker and no analyst.
        "version",
    }
)

# Statements and clauses that write or lock, wherever they appear in a query.
_WRITING_NODES: tuple[type[exp.Expr], ...] = (
    exp.DML,
    exp.DDL,
    exp.Into,
    exp.Lock,
    exp.Command,
    exp.Copy,
    exp.Set,
    exp.Transaction,
    exp.Grant,
    exp.TruncateTable,
)


class GuardReason(StrEnum):
    EMPTY = "empty"
    TOO_LONG = "too_long"
    PARSE_ERROR = "parse_error"
    MULTIPLE_STATEMENTS = "multiple_statements"
    NOT_A_QUERY = "not_a_query"
    DATA_MODIFICATION = "data_modification"
    FORBIDDEN_TABLE = "forbidden_table"
    FORBIDDEN_SCHEMA = "forbidden_schema"
    FORBIDDEN_FUNCTION = "forbidden_function"
    UNSUPPORTED_LIMIT = "unsupported_limit"


class SqlRejectedError(Exception):
    """The SQL may not run. ``message`` is safe to show to the analyst."""

    def __init__(self, reason: GuardReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True, slots=True)
class GuardedSql:
    # Pretty-printed, comment-free SQL with the row limit applied: both what
    # runs and what the analyst sees, so the two can never differ.
    sql: str
    # Rows the analyst may receive; the query asks for one more, so a full
    # extra row means the result was truncated.
    row_cap: int


def guard_sql(sql: str, *, max_rows: int) -> GuardedSql:
    """Return the runnable form of ``sql`` or raise ``SqlRejectedError`` with the reason."""
    if not sql.strip():
        raise SqlRejectedError(GuardReason.EMPTY, "The model returned no SQL.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SqlRejectedError(
            GuardReason.TOO_LONG, f"The SQL is longer than {MAX_SQL_LENGTH:,} characters."
        )

    tree = _parse_single_statement(sql)
    # PostgreSQL folds unquoted identifiers to lower case and keeps quoted
    # ones as written; comparing after the same folding matches its lookup.
    tree = normalize_identifiers(tree, dialect=_DIALECT)
    if not isinstance(tree, exp.Query):
        raise SqlRejectedError(GuardReason.NOT_A_QUERY, "Only SELECT queries may run.")

    _reject_writes(tree)
    _reject_forbidden_functions(tree)
    _reject_forbidden_tables(tree)
    _apply_row_cap(tree, max_rows + 1)
    return GuardedSql(sql=tree.sql(dialect=_DIALECT, pretty=True, comments=False), row_cap=max_rows)


def _parse_single_statement(sql: str) -> exp.Expr:
    try:
        statements = [s for s in sqlglot.parse(sql, read=_DIALECT) if s is not None]
    except ParseError as error:
        raise SqlRejectedError(GuardReason.PARSE_ERROR, "The SQL could not be parsed.") from error
    if not statements:
        raise SqlRejectedError(GuardReason.EMPTY, "The model returned no SQL.")
    if len(statements) > 1:
        raise SqlRejectedError(GuardReason.MULTIPLE_STATEMENTS, "Only a single statement may run.")
    return statements[0]


def _reject_writes(tree: exp.Query) -> None:
    for node in tree.walk():
        if isinstance(node, _WRITING_NODES):
            raise SqlRejectedError(
                GuardReason.DATA_MODIFICATION,
                "The query may only read data, never change or lock it.",
            )


def _function_name(node: exp.Func) -> str:
    """The name PostgreSQL will see for this call.

    sqlglot gives known functions its own class names (generate_series is
    ExplodingGenerateSeries), so the name is read from the SQL that will be
    generated, which is what actually runs.
    """
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    match = _CALL_NAME.match(node.sql(dialect=_DIALECT))
    return match.group(1).lower() if match else node.sql_name().lower()


def _reject_forbidden_functions(tree: exp.Query) -> None:
    for node in tree.find_all(exp.Func):
        name = _function_name(node)
        # A schema-qualified call (pg_catalog.pg_sleep, public.f) can reach
        # functions the plain name would not; the views need none of them.
        qualified = isinstance(node.parent, exp.Dot) and node.parent.expression is node
        if (
            qualified
            or name in _FORBIDDEN_FUNCTIONS
            or name.startswith(_FORBIDDEN_FUNCTION_PREFIXES)
        ):
            raise SqlRejectedError(
                GuardReason.FORBIDDEN_FUNCTION, f"The function {name}() is not allowed."
            )


def _reject_forbidden_tables(tree: exp.Query) -> None:
    checked: set[int] = set()
    for scope in traverse_scope(tree):
        for table in scope.tables:
            _check_table(scope, table)
            checked.add(id(table))
    # Every table must have been seen through a scope; one the scope walk
    # missed is in a construct the guard does not understand.
    for table in tree.find_all(exp.Table):
        if id(table) not in checked:
            raise SqlRejectedError(
                GuardReason.FORBIDDEN_TABLE,
                f"The table {table.sql(dialect=_DIALECT)} is not allowed.",
            )


def _check_table(scope: Scope, table: exp.Table) -> None:
    if isinstance(table.this, exp.Func):
        name = _function_name(table.this)
        if name not in _TABLE_FUNCTIONS:
            raise SqlRejectedError(
                GuardReason.FORBIDDEN_FUNCTION, f"The function {name}() is not allowed."
            )
        return

    schema, catalog = table.db, table.catalog
    if catalog or (schema and schema != ALLOWED_SCHEMA):
        raise SqlRejectedError(
            GuardReason.FORBIDDEN_SCHEMA,
            f"Only the {ALLOWED_SCHEMA} views may be queried, not {table.sql(dialect=_DIALECT)}.",
        )
    # A CTE is visible only in the query that defines it (and that query's
    # subqueries); the scope knows which names refer to one here.
    if (
        not schema
        and isinstance(scope.sources.get(table.alias_or_name), Scope)
        and (table.name in scope.cte_sources)
    ):
        return
    if table.name not in ALLOWED_VIEWS:
        raise SqlRejectedError(
            GuardReason.FORBIDDEN_TABLE,
            f"The table {table.name} is not allowed; use " + ", ".join(sorted(ALLOWED_VIEWS)) + ".",
        )


def _apply_row_cap(tree: exp.Query, limit: int) -> None:
    current = tree.args.get("limit")
    if current is None:
        tree.limit(limit, copy=False)
        return
    value = current.expression if isinstance(current, exp.Limit) else None
    if not (isinstance(value, exp.Literal) and value.is_int):
        raise SqlRejectedError(
            GuardReason.UNSUPPORTED_LIMIT, "LIMIT must be a whole number when the query has one."
        )
    if int(value.name) > limit:
        tree.limit(limit, copy=False)
