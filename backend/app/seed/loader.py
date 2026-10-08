"""Streams generated rows into PostgreSQL with COPY.

COPY sends rows as one continuous stream instead of one statement per row,
which is what makes millions of rows load in minutes. Orders and their
items are copied in batches: one psycopg connection runs one COPY at a
time, and an order must reach the table before the foreign keys of its
items are checked.

The loader runs inside the caller's transaction and never commits, so a
failed load leaves the previous data untouched.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import batched
from typing import Any

from psycopg import Connection, Cursor, sql
from sqlalchemy.orm import Session

from app.seed.generator import CustomerRow, OrderItemRow, OrderRow, ProductRow, SalesData

# Parents before children, the order in which rows must be loaded.
SALES_TABLES = ("customers", "products", "orders", "order_items")
ORDERS_PER_BATCH = 50_000

CUSTOMER_COLUMNS = ("id", "name", "email", "country", "signed_up_at")
PRODUCT_COLUMNS = ("id", "name", "category", "price")
ORDER_COLUMNS = ("id", "customer_id", "status", "channel", "total", "created_at")
ORDER_ITEM_COLUMNS = ("order_id", "product_id", "quantity", "unit_price")

ProgressCallback = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class TableStats:
    table: str
    rows: int
    total_bytes: int


def psycopg_connection(session: Session) -> Connection[Any]:
    """The psycopg connection behind ``session``'s current transaction.

    COPY is a psycopg feature that SQLAlchemy does not expose. Using the
    session's own connection keeps the load inside the session's transaction.
    """
    connection = session.connection().connection.driver_connection
    if not isinstance(connection, Connection):
        raise TypeError(f"COPY needs a psycopg connection, not {type(connection).__name__}")
    return connection


def load_sales_data(
    connection: Connection[Any],
    data: SalesData,
    *,
    orders_per_batch: int = ORDERS_PER_BATCH,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Replace every sales row with ``data``, then refresh planner statistics.

    ``on_progress`` receives the number of orders loaded so far after each batch.
    """
    with connection.cursor() as cursor:
        cursor.execute(_truncate_sales_tables())
        _copy(cursor, "customers", CUSTOMER_COLUMNS, map(_customer_record, data.customers))
        _copy(cursor, "products", PRODUCT_COLUMNS, map(_product_record, data.products))

        loaded = 0
        for batch in batched(data.orders, orders_per_batch):
            _copy(cursor, "orders", ORDER_COLUMNS, (_order_record(order) for order, _ in batch))
            _copy(
                cursor,
                "order_items",
                ORDER_ITEM_COLUMNS,
                (_item_record(item) for _, items in batch for item in items),
            )
            loaded += len(batch)
            if on_progress is not None:
                on_progress(loaded)

        for table in ("customers", "products", "orders"):
            cursor.execute(_continue_identity_after_max_id(table))
        # Fresh statistics let the planner see millions of rows straight away
        # instead of waiting for autovacuum to notice.
        cursor.execute(
            sql.SQL("ANALYZE {}").format(sql.SQL(", ").join(map(sql.Identifier, SALES_TABLES)))
        )


def table_stats(connection: Connection[Any]) -> list[TableStats]:
    """Exact row counts and on-disk sizes (with indexes and TOAST) of the sales tables."""
    with connection.cursor() as cursor:
        stats = []
        for table in SALES_TABLES:
            cursor.execute(
                sql.SQL("SELECT count(*), pg_total_relation_size({name}) FROM {table}").format(
                    name=sql.Literal(table), table=sql.Identifier(table)
                )
            )
            ((rows, total_bytes),) = cursor.fetchall()
            stats.append(TableStats(table, rows, total_bytes))
        return stats


def cents_to_text(cents: int) -> str:
    """Format non-negative integer cents as a numeric literal: 1999 -> "19.99"."""
    return f"{cents // 100}.{cents % 100:02d}"


# Records in the column order above. Money goes over as numeric text built
# from integer cents, so no float or Decimal rounding is involved.


def _customer_record(customer: CustomerRow) -> tuple[Any, ...]:
    return (customer.id, customer.name, customer.email, customer.country, customer.signed_up_at)


def _product_record(product: ProductRow) -> tuple[Any, ...]:
    return (product.id, product.name, product.category, cents_to_text(product.price_cents))


def _order_record(order: OrderRow) -> tuple[Any, ...]:
    return (
        order.id,
        order.customer_id,
        order.status,
        order.channel,
        cents_to_text(order.total_cents),
        order.created_at,
    )


def _item_record(item: OrderItemRow) -> tuple[Any, ...]:
    return (item.order_id, item.product_id, item.quantity, cents_to_text(item.unit_price_cents))


def _copy(
    cursor: Cursor[Any], table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]
) -> None:
    statement = sql.SQL("COPY {table} ({columns}) FROM STDIN").format(
        table=sql.Identifier(table), columns=sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    with cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def _truncate_sales_tables() -> sql.Composed:
    return sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
        sql.SQL(", ").join(map(sql.Identifier, SALES_TABLES))
    )


def _continue_identity_after_max_id(table: str) -> sql.Composed:
    # COPY writes the generated ids itself, which leaves the identity sequence
    # behind; without this, the next ordinary insert would collide with id 1.
    return sql.SQL(
        "SELECT setval(pg_get_serial_sequence({name}, 'id'), coalesce(max(id), 0) + 1, false) "
        "FROM {table}"
    ).format(name=sql.Literal(table), table=sql.Identifier(table))
