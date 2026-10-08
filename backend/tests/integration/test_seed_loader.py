from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import Mock

import pytest
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.orm import Session, scoped_session

from app.models import Customer, OrderChannel, OrderStatus
from app.seed.generator import GeneratedOrder, SalesData, SeedScale, generate_sales_data
from app.seed.loader import cents_to_text, load_sales_data, psycopg_connection, table_stats

END_DATE = date(2026, 10, 1)
TINY = SeedScale("tiny", customers=300, products=40, orders=3_000)

# A fingerprint of every 7th order and its items: enough rows to catch any
# difference, and the same rows for every load of the same data.
SAMPLE_CHECKSUM = """
    SELECT md5(string_agg(line, '\n' ORDER BY line))
    FROM (
        SELECT concat_ws('|', o.id, o.customer_id, o.status, o.channel, o.total,
                         extract(epoch FROM o.created_at),
                         i.product_id, i.quantity, i.unit_price) AS line
        FROM orders AS o
        JOIN order_items AS i ON i.order_id = o.id
        WHERE o.id % 7 = 0
    ) AS sample
"""


@pytest.fixture
def session(db_session: scoped_session[Session]) -> Session:
    return db_session()


@pytest.fixture
def connection(session: Session) -> Connection[Any]:
    return psycopg_connection(session)


def seed(connection: Connection[Any], seed: int = 42, scale: SeedScale = TINY) -> None:
    load_sales_data(connection, generate_sales_data(scale, seed=seed, end_date=END_DATE))


def scalar(session: Session, sql: str) -> Any:
    return session.execute(text(sql)).scalar_one()


def test_load_inserts_every_generated_row(session: Session, connection: Connection[Any]) -> None:
    data = generate_sales_data(TINY, seed=42, end_date=END_DATE)
    orders = list(data.orders)
    replay = SalesData(data.customers, data.products, iter(orders))

    load_sales_data(connection, replay)

    counts = {stats.table: stats.rows for stats in table_stats(connection)}
    assert counts == {
        "customers": 300,
        "products": 40,
        "orders": 3_000,
        "order_items": sum(len(order.items) for order in orders),
    }


def test_loaded_order_totals_equal_the_sum_of_their_items(
    session: Session, connection: Connection[Any]
) -> None:
    seed(connection)

    mismatches = scalar(
        session,
        """
        SELECT count(*) FROM orders AS o
        LEFT JOIN (
            SELECT order_id, sum(quantity * unit_price) AS items_total
            FROM order_items GROUP BY order_id
        ) AS i ON i.order_id = o.id
        WHERE i.items_total IS DISTINCT FROM o.total
        """,
    )

    assert mismatches == 0


def test_loaded_rows_keep_exact_money_and_utc_timestamps(
    session: Session, connection: Connection[Any]
) -> None:
    data = generate_sales_data(TINY, seed=42, end_date=END_DATE)
    first = next(data.orders)
    load_sales_data(connection, SalesData(data.customers, data.products, iter([first])))

    total, created_at = session.execute(
        text("SELECT total, created_at FROM orders WHERE id = :id"), {"id": first.order.id}
    ).one()

    assert str(total) == cents_to_text(first.order.total_cents)
    assert created_at == first.order.created_at


def test_loaded_statuses_and_channels_are_the_allowed_values(
    session: Session, connection: Connection[Any]
) -> None:
    seed(connection)

    statuses = set(session.scalars(text("SELECT DISTINCT status FROM orders")))
    channels = set(session.scalars(text("SELECT DISTINCT channel FROM orders")))

    assert statuses == set(OrderStatus)
    assert channels == set(OrderChannel)


def test_reloading_replaces_the_data_with_identical_rows(
    session: Session, connection: Connection[Any]
) -> None:
    seed(connection)
    first = scalar(session, SAMPLE_CHECKSUM)

    seed(connection)

    assert scalar(session, SAMPLE_CHECKSUM) == first
    assert scalar(session, "SELECT count(*) FROM orders") == 3_000


def test_a_different_seed_loads_different_rows(
    session: Session, connection: Connection[Any]
) -> None:
    seed(connection, seed=1)
    first = scalar(session, SAMPLE_CHECKSUM)

    seed(connection, seed=2)

    assert scalar(session, SAMPLE_CHECKSUM) != first


def test_new_rows_get_ids_after_the_loaded_ones(
    session: Session, connection: Connection[Any]
) -> None:
    seed(connection)

    customer = Customer(
        name="Late Signup",
        email="late@example.com",
        country="NL",
        signed_up_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    session.add(customer)
    session.flush()

    assert customer.id == 301


def test_a_failed_load_leaves_the_previous_data_untouched(
    session: Session, connection: Connection[Any]
) -> None:
    seed(connection)
    before = scalar(session, SAMPLE_CHECKSUM)
    data = generate_sales_data(TINY, seed=99, end_date=END_DATE)

    def failing_orders() -> Iterator[GeneratedOrder]:
        yield next(data.orders)
        raise RuntimeError("generator crashed")

    # The caller's transaction, here a savepoint, is what protects the old data.
    with pytest.raises(RuntimeError, match="generator crashed"), connection.transaction():
        load_sales_data(
            connection,
            SalesData(data.customers, data.products, failing_orders()),
            orders_per_batch=1,
        )

    assert scalar(session, SAMPLE_CHECKSUM) == before


def test_progress_is_reported_after_each_batch(connection: Connection[Any]) -> None:
    reported: list[int] = []

    load_sales_data(
        connection,
        generate_sales_data(SeedScale("micro", 50, 10, 1_200), seed=3, end_date=END_DATE),
        orders_per_batch=500,
        on_progress=reported.append,
    )

    assert reported == [500, 1_000, 1_200]


def test_load_refreshes_planner_statistics(session: Session, connection: Connection[Any]) -> None:
    seed(connection)

    estimated = scalar(session, "SELECT reltuples::bigint FROM pg_class WHERE relname = 'orders'")

    assert estimated == 3_000


def test_table_stats_report_sizes_of_the_sales_tables(connection: Connection[Any]) -> None:
    seed(connection)

    stats = table_stats(connection)

    assert [s.table for s in stats] == ["customers", "products", "orders", "order_items"]
    assert all(s.rows > 0 and s.total_bytes > 0 for s in stats)


@pytest.mark.parametrize(
    ("cents", "expected"), [(0, "0.00"), (5, "0.05"), (1_999, "19.99"), (123_400, "1234.00")]
)
def test_cents_are_formatted_as_numeric_text(cents: int, expected: str) -> None:
    assert cents_to_text(cents) == expected


def test_psycopg_connection_rejects_another_driver() -> None:
    session = Mock(spec=Session)
    session.connection.return_value.connection.driver_connection = object()

    with pytest.raises(TypeError, match="COPY needs a psycopg connection, not object"):
        psycopg_connection(session)
