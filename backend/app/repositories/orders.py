"""Queries for orders."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, literal, select, tuple_
from sqlalchemy.orm import Session, contains_eager

from app.models import Customer, Order, OrderChannel, OrderSort, OrderStatus


@dataclass(frozen=True, slots=True)
class OrderFilters:
    """Conditions an order must meet; ``None`` or empty means "any"."""

    statuses: tuple[OrderStatus, ...] = ()
    country: str | None = None
    customer_id: int | None = None
    channel: OrderChannel | None = None
    created_from: datetime | None = None
    """Inclusive lower bound on ``created_at``."""
    created_before: datetime | None = None
    """Exclusive upper bound on ``created_at``."""
    min_total: Decimal | None = None
    max_total: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Keyset:
    """Where the previous page ended: its last row's sort value and id."""

    value: datetime | Decimal
    id: int


_SORT_COLUMNS = {
    OrderSort.CREATED_AT: Order.created_at,
    OrderSort.TOTAL: Order.total,
}


def build_list_statement(
    filters: OrderFilters, sort: OrderSort, after: Keyset | None, limit: int
) -> Select[Order]:
    """The query behind the orders list.

    Public so the EXPLAIN script measures exactly the statement the API runs.
    Each order comes with its customer from the same query, through a join.
    """
    sort_column = _SORT_COLUMNS[sort]
    statement = (
        select(Order)
        .join(Order.customer)
        .options(contains_eager(Order.customer))
        .where(*_conditions(filters))
        # id makes the order total, so rows that tie on the sort value still
        # have one fixed position and a page boundary can fall between them.
        .order_by(sort_column.desc(), Order.id.desc())
        .limit(limit)
    )
    if after is not None:
        # A row-value comparison rather than "a < x OR (a = x AND id < y)":
        # PostgreSQL turns it directly into a range on an index over
        # (sort column, id). The parameters carry the column types so the
        # comparison is not between bigint and integer.
        statement = statement.where(
            tuple_(sort_column, Order.id)
            < tuple_(literal(after.value, sort_column.type), literal(after.id, Order.id.type))
        )
    return statement


def _conditions(filters: OrderFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.statuses:
        conditions.append(Order.status.in_(filters.statuses))
    if filters.country is not None:
        conditions.append(Customer.country == filters.country)
    if filters.customer_id is not None:
        conditions.append(Order.customer_id == filters.customer_id)
    if filters.channel is not None:
        conditions.append(Order.channel == filters.channel)
    if filters.created_from is not None:
        conditions.append(Order.created_at >= filters.created_from)
    if filters.created_before is not None:
        conditions.append(Order.created_at < filters.created_before)
    if filters.min_total is not None:
        conditions.append(Order.total >= filters.min_total)
    if filters.max_total is not None:
        conditions.append(Order.total <= filters.max_total)
    return conditions


class OrderRepository:
    """Reads orders within the caller's session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_page(
        self, filters: OrderFilters, sort: OrderSort, after: Keyset | None, limit: int
    ) -> Sequence[Order]:
        """Up to ``limit`` matching orders after ``after``, each with its customer loaded."""
        return self._session.scalars(build_list_statement(filters, sort, after, limit)).all()
