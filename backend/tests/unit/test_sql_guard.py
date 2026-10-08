"""The SQL guard decides which model-written SQL may run at all.

Every rejection case is something a model could produce by mistake or be
talked into producing by a hostile question. The guard is not the only
defense (the read-only role refuses the same things on its own), but it is
the one that explains the refusal, so each case also pins the reason.
"""

import pytest
import sqlglot
from sqlglot import exp

from app.ai.sql_guard import GuardReason, SqlRejectedError, guard_sql

MAX_ROWS = 1000


def _reason(sql: str) -> GuardReason:
    with pytest.raises(SqlRejectedError) as caught:
        guard_sql(sql, max_rows=MAX_ROWS)
    return caught.value.reason


def _limit(sql: str) -> int:
    limit = sqlglot.parse_one(sql, read="postgres").args["limit"]
    assert isinstance(limit, exp.Limit)
    return int(limit.expression.name)


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        # Nothing to run.
        ("", GuardReason.EMPTY),
        ("  ;  ", GuardReason.EMPTY),
        ("SELECT 1 FROM v_orders WHERE (", GuardReason.PARSE_ERROR),
        # Statements other than a query.
        ("DELETE FROM v_orders", GuardReason.NOT_A_QUERY),
        ("UPDATE v_orders SET total = 0", GuardReason.NOT_A_QUERY),
        (
            "INSERT INTO v_products (name, category, price) VALUES ('x', 'y', 1)",
            GuardReason.NOT_A_QUERY,
        ),
        (
            "MERGE INTO v_orders USING v_orders AS s ON true WHEN MATCHED THEN DELETE",
            GuardReason.NOT_A_QUERY,
        ),
        ("DROP TABLE users", GuardReason.NOT_A_QUERY),
        ("TRUNCATE orders", GuardReason.NOT_A_QUERY),
        ("CREATE TABLE stolen AS SELECT * FROM v_orders", GuardReason.NOT_A_QUERY),
        ("ALTER ROLE datapilot_readonly SET statement_timeout = 0", GuardReason.NOT_A_QUERY),
        ("GRANT SELECT ON users TO datapilot_readonly", GuardReason.NOT_A_QUERY),
        ("COPY users TO STDOUT", GuardReason.NOT_A_QUERY),
        ("COPY (SELECT * FROM v_orders) TO '/tmp/orders.csv'", GuardReason.NOT_A_QUERY),
        ("SET statement_timeout = 0", GuardReason.NOT_A_QUERY),
        ("BEGIN READ WRITE", GuardReason.NOT_A_QUERY),
        ("EXPLAIN ANALYZE SELECT * FROM v_orders", GuardReason.NOT_A_QUERY),
        ("VALUES (1)", GuardReason.NOT_A_QUERY),
        # More than one statement, however they are separated.
        ("SELECT 1; DROP TABLE users", GuardReason.MULTIPLE_STATEMENTS),
        ("SELECT id FROM v_orders; SELECT id FROM v_customers", GuardReason.MULTIPLE_STATEMENTS),
        ("SELECT 1 /* harmless */; DELETE FROM users", GuardReason.MULTIPLE_STATEMENTS),
        # Writes or locks hidden inside a query.
        (
            "WITH gone AS (DELETE FROM v_orders RETURNING *) SELECT * FROM gone",
            GuardReason.DATA_MODIFICATION,
        ),
        (
            "WITH x AS (UPDATE v_orders SET total = 0 RETURNING id) SELECT id FROM x",
            GuardReason.DATA_MODIFICATION,
        ),
        (
            "WITH x AS (INSERT INTO v_customers (country) VALUES ('US') RETURNING id) "
            "SELECT * FROM x",
            GuardReason.DATA_MODIFICATION,
        ),
        ("SELECT * INTO stolen FROM v_orders", GuardReason.DATA_MODIFICATION),
        ("SELECT * FROM v_orders FOR UPDATE", GuardReason.DATA_MODIFICATION),
        ("SELECT * FROM v_orders FOR SHARE", GuardReason.DATA_MODIFICATION),
        # Tables that are not the curated views.
        ("SELECT * FROM users", GuardReason.FORBIDDEN_TABLE),
        ("SELECT * FROM orders", GuardReason.FORBIDDEN_TABLE),
        ("SELECT * FROM pg_class", GuardReason.FORBIDDEN_TABLE),
        ("SELECT rolname, rolpassword FROM pg_authid", GuardReason.FORBIDDEN_TABLE),
        (
            "SELECT * FROM v_orders o JOIN users u ON u.id = o.customer_id",
            GuardReason.FORBIDDEN_TABLE,
        ),
        (
            "SELECT * FROM v_orders WHERE customer_id IN (SELECT id FROM users)",
            GuardReason.FORBIDDEN_TABLE,
        ),
        (
            "SELECT id FROM v_orders WHERE EXISTS (SELECT 1 FROM customers)",
            GuardReason.FORBIDDEN_TABLE,
        ),
        ("SELECT id FROM v_orders UNION SELECT id FROM users", GuardReason.FORBIDDEN_TABLE),
        ("WITH v AS (SELECT * FROM v_orders) SELECT * FROM users", GuardReason.FORBIDDEN_TABLE),
        ("WITH v AS (SELECT * FROM users) SELECT * FROM v", GuardReason.FORBIDDEN_TABLE),
        # A CTE named "users" only covers its own query; the outer "users"
        # is the real table.
        (
            "SELECT * FROM (WITH users AS (SELECT 1 AS id) SELECT * FROM users) a, users b",
            GuardReason.FORBIDDEN_TABLE,
        ),
        # Quoted identifiers keep their case in PostgreSQL: "V_ORDERS" is not v_orders.
        ('SELECT * FROM "V_ORDERS"', GuardReason.FORBIDDEN_TABLE),
        # Schemas other than analytics, however they are spelled.
        ("SELECT * FROM public.users", GuardReason.FORBIDDEN_SCHEMA),
        ('SELECT * FROM "public"."users"', GuardReason.FORBIDDEN_SCHEMA),
        ("SELECT * FROM PUBLIC.Orders", GuardReason.FORBIDDEN_SCHEMA),
        ("SELECT * FROM public.v_orders", GuardReason.FORBIDDEN_SCHEMA),
        ("SELECT table_name FROM information_schema.tables", GuardReason.FORBIDDEN_SCHEMA),
        ("SELECT * FROM pg_catalog.pg_authid", GuardReason.FORBIDDEN_SCHEMA),
        ("SELECT * FROM datapilot.analytics.v_orders", GuardReason.FORBIDDEN_SCHEMA),
        # Dangerous functions, anywhere and in any case.
        ("SELECT pg_sleep(10)", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT id FROM v_orders WHERE pg_sleep(1) IS NOT NULL", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT PG_SLEEP(1)", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT pg_catalog.pg_sleep(1)", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT analytics.custom_function()", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT pg_read_file('/etc/passwd')", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT * FROM pg_ls_dir('.')", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT * FROM v_orders, LATERAL pg_ls_dir('.') AS d", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT lo_import('/etc/passwd')", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT dblink_exec('host=evil', 'DROP TABLE users')", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT set_config('statement_timeout', '0', false)", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT current_setting('data_directory')", GuardReason.FORBIDDEN_FUNCTION),
        ("SELECT pg_terminate_backend(1)", GuardReason.FORBIDDEN_FUNCTION),
        # These run SQL given as a string, out of the guard's sight.
        (
            "SELECT query_to_xml('SELECT * FROM public.users', true, true, '')",
            GuardReason.FORBIDDEN_FUNCTION,
        ),
        (
            "SELECT * FROM ts_stat('SELECT to_tsvector(email) FROM public.users')",
            GuardReason.FORBIDDEN_FUNCTION,
        ),
        ("SELECT nextval('orders_id_seq')", GuardReason.FORBIDDEN_FUNCTION),
        # Only value generators may stand in for a table.
        ("SELECT * FROM json_each('{\"a\": 1}')", GuardReason.FORBIDDEN_FUNCTION),
        # Row limits the guard cannot bound.
        ("SELECT id FROM v_orders LIMIT (SELECT 5)", GuardReason.UNSUPPORTED_LIMIT),
    ],
)
def test_guard_rejects_unsafe_sql_with_its_reason(sql: str, reason: GuardReason) -> None:
    assert _reason(sql) == reason


def test_guard_rejects_sql_longer_than_the_limit() -> None:
    sql = "SELECT id FROM v_orders WHERE id IN (" + ", ".join(["1"] * 5000) + ")"  # noqa: S608

    assert _reason(sql) == GuardReason.TOO_LONG


def test_rejection_message_names_the_offending_table() -> None:
    with pytest.raises(SqlRejectedError) as caught:
        guard_sql("SELECT * FROM v_orders JOIN users ON true", max_rows=MAX_ROWS)

    assert "users" in caught.value.message


# Shared with the integration test that runs each one on PostgreSQL.
ACCEPTED_SQL = [
    "SELECT id, total FROM v_orders",
    "select ID, Total from V_ORDERS",
    'SELECT "id" FROM "v_orders"',
    "SELECT id FROM analytics.v_orders",
    "SELECT id FROM ANALYTICS.V_ORDERS",
    # A legitimate CTE, referenced twice.
    """
    WITH monthly AS (
        SELECT date_trunc('month', created_at) AS month, sum(total) AS revenue
        FROM v_orders WHERE status = 'paid' GROUP BY 1
    )
    SELECT m.month, m.revenue, m.revenue - p.revenue AS change
    FROM monthly m LEFT JOIN monthly p ON p.month = m.month - interval '1 month'
    ORDER BY m.month
    """,
    # A legitimate join across every view.
    """
    SELECT c.country, p.category, sum(i.quantity * i.unit_price) AS revenue
    FROM v_orders o
    JOIN v_customers c ON c.id = o.customer_id
    JOIN v_order_items i ON i.order_id = o.id
    JOIN v_products p ON p.id = i.product_id
    WHERE o.status = 'paid'
    GROUP BY c.country, p.category
    ORDER BY revenue DESC
    """,
    # A legitimate union.
    """
    SELECT 'web' AS channel, count(*) FROM v_orders WHERE channel = 'web'
    UNION ALL
    SELECT 'mobile', count(*) FROM v_orders WHERE channel = 'mobile'
    ORDER BY 1
    """,
    # Window functions and date arithmetic.
    """
    SELECT id, total,
           rank() OVER (PARTITION BY customer_id ORDER BY total DESC) AS position,
           extract(year FROM created_at) AS year, to_char(created_at, 'YYYY-MM') AS month
    FROM v_orders WHERE created_at >= now() - interval '90 days'
    """,
    # Set-returning functions that only generate values.
    """
    SELECT m::date AS month, count(o.id)
    FROM generate_series(date '2025-01-01', date '2025-12-01', interval '1 month') AS m
    LEFT JOIN v_orders o ON date_trunc('month', o.created_at) = m
    GROUP BY m ORDER BY m
    """,
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total) AS median FROM v_orders",
    "SELECT unnest(ARRAY['paid', 'refunded']) AS status",
    "SELECT name FROM v_products WHERE name LIKE '%Lamp%' AND category <> 'Garden'",
    "SELECT id FROM v_orders WHERE created_at::text LIKE '%10:30%'",
    "SELECT count(*) FROM v_orders WHERE status IN ('paid', 'refunded') AND total > 100",
]


@pytest.mark.parametrize("sql", ACCEPTED_SQL)
def test_guard_accepts_read_only_queries_over_the_analytics_views(sql: str) -> None:
    guarded = guard_sql(sql, max_rows=MAX_ROWS)

    assert sqlglot.parse_one(guarded.sql, read="postgres") is not None


def test_guard_adds_a_limit_one_above_the_row_cap_to_detect_truncation() -> None:
    guarded = guard_sql("SELECT id FROM v_orders ORDER BY id", max_rows=MAX_ROWS)

    assert _limit(guarded.sql) == MAX_ROWS + 1
    assert guarded.row_cap == MAX_ROWS


def test_guard_keeps_a_smaller_limit_from_the_query() -> None:
    guarded = guard_sql("SELECT id FROM v_orders ORDER BY total DESC LIMIT 10", max_rows=MAX_ROWS)

    assert _limit(guarded.sql) == 10


def test_guard_lowers_a_limit_above_the_row_cap() -> None:
    guarded = guard_sql("SELECT id FROM v_orders LIMIT 50000 OFFSET 5", max_rows=MAX_ROWS)

    assert _limit(guarded.sql) == MAX_ROWS + 1
    assert "OFFSET 5" in guarded.sql


def test_guard_replaces_limit_all_with_the_row_cap() -> None:
    guarded = guard_sql("SELECT id FROM v_orders LIMIT ALL", max_rows=MAX_ROWS)

    assert _limit(guarded.sql) == MAX_ROWS + 1


def test_guard_limits_a_union_as_a_whole() -> None:
    guarded = guard_sql(
        "SELECT id FROM v_orders UNION SELECT id FROM v_customers ORDER BY 1", max_rows=MAX_ROWS
    )

    tree = sqlglot.parse_one(guarded.sql, read="postgres")
    assert isinstance(tree, exp.Union)
    assert _limit(guarded.sql) == MAX_ROWS + 1


def test_guard_drops_comments_so_none_can_reopen_as_sql() -> None:
    # A line comment regenerated as /* ... */ would end at the "*/" inside
    # it and turn the rest into a second statement.
    guarded = guard_sql("SELECT id FROM v_orders -- */; DROP TABLE users", max_rows=MAX_ROWS)

    assert "DROP" not in guarded.sql
    assert "--" not in guarded.sql
    assert "/*" not in guarded.sql


def test_guard_pretty_prints_the_sql_it_returns() -> None:
    guarded = guard_sql(
        "select status, count(*) from v_orders group by status order by 2 desc",
        max_rows=MAX_ROWS,
    )

    assert guarded.sql.splitlines()[0] == "SELECT"
    assert "GROUP BY" in guarded.sql


def test_guard_rejects_a_table_its_scope_analysis_did_not_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Stands in for a construct sqlglot's scope walk does not understand:
    # the guard must refuse what it could not check rather than let it pass.
    monkeypatch.setattr("app.ai.sql_guard.traverse_scope", lambda _tree: [])

    assert _reason("SELECT id FROM v_orders") == GuardReason.FORBIDDEN_TABLE
