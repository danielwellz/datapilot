"""Measure the query plans of the orders endpoints with EXPLAIN (ANALYZE, BUFFERS).

Each scenario calls the same repository code the API calls; ``scripts.plans``
records its SQL and explains it with the real parameters.

Two scenarios fetch the same deep page, once with the keyset cursor the API
uses and once with OFFSET, which the API never uses; the pair exists only as
evidence of why.

Usage, from ``backend/`` against the database in ``DATABASE_URL``::

    uv run python -m scripts.explain_orders [--runs 10] [--depth 1000000] [--only NAME ...]
"""

import argparse
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Order, OrderSort, OrderStatus
from app.repositories.meta import MetaRepository
from app.repositories.orders import Keyset, OrderFilters, OrderRepository, build_list_statement
from app.schemas.orders import DEFAULT_PAGE_SIZE
from app.services.meta import MetaService
from scripts.plans import Scenario, add_arguments, explain

# The API asks for one row more than the page, to learn whether a next page exists.
PAGE_QUERY_LIMIT = DEFAULT_PAGE_SIZE + 1


def build_scenarios(session: Session, depth: int) -> list[Scenario]:
    """The queries worth measuring, with parameters taken from the data itself."""
    orders = OrderRepository(session)
    _, last = MetaRepository(session).order_time_bounds()
    if last is None:
        raise SystemExit("There are no orders to measure. Load data first: make seed scale=full")
    busiest_customer = session.scalars(
        select(Order.customer_id)
        .group_by(Order.customer_id)
        .order_by(func.count().desc(), Order.customer_id)
        .limit(1)
    ).one()
    deep = _deep_position(session, depth)
    newest = OrderFilters()
    by_date = OrderSort.CREATED_AT

    def keyset_page() -> object:
        return orders.list_page(newest, by_date, deep, PAGE_QUERY_LIMIT)

    def offset_page() -> object:
        statement = build_list_statement(newest, by_date, None, PAGE_QUERY_LIMIT).offset(depth)
        return session.scalars(statement).all()

    return [
        Scenario(
            "list-default",
            "First page, newest first, no filters",
            lambda: orders.list_page(newest, by_date, None, PAGE_QUERY_LIMIT),
        ),
        Scenario(
            "list-country-90-days",
            "Country DE, the last 90 days of data",
            lambda: orders.list_page(
                OrderFilters(country="DE", created_from=last - timedelta(days=90)),
                by_date,
                None,
                PAGE_QUERY_LIMIT,
            ),
        ),
        Scenario(
            "list-customer-history",
            f"Customer {busiest_customer}, the one with the most orders",
            lambda: orders.list_page(
                OrderFilters(customer_id=busiest_customer), by_date, None, PAGE_QUERY_LIMIT
            ),
        ),
        Scenario(
            "list-by-total",
            "First page, largest total first",
            lambda: orders.list_page(newest, OrderSort.TOTAL, None, PAGE_QUERY_LIMIT),
        ),
        Scenario(
            "list-deep-keyset",
            f"The page after row {depth:,}, through a keyset cursor (what the API runs)",
            keyset_page,
        ),
        Scenario(
            "list-deep-offset",
            f"The same page with OFFSET {depth:,} (comparison only; the API never does this)",
            offset_page,
        ),
        Scenario(
            "list-rare-filters",
            "Cancelled orders from DK, newest first (about 0.02% of rows match)",
            lambda: orders.list_page(
                OrderFilters(statuses=(OrderStatus.CANCELLED,), country="DK"),
                by_date,
                None,
                PAGE_QUERY_LIMIT,
            ),
        ),
        Scenario(
            "order-detail",
            f"Order {deep.id} with its customer and items",
            lambda: orders.get_with_details(deep.id),
        ),
        Scenario(
            "meta", "Filter options and order date bounds", MetaService(session).filter_options
        ),
    ]


def _deep_position(session: Session, depth: int) -> Keyset:
    """The position of row ``depth`` (1-based) in the default order.

    Found with OFFSET once, at setup, so both deep-page scenarios start after
    the same row and return the same page.
    """
    row = session.execute(
        select(Order.created_at, Order.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset(depth - 1)
        .limit(1)
    ).one_or_none()
    if row is None:
        raise SystemExit(f"There are fewer than {depth} orders; choose a smaller --depth.")
    return Keyset(value=row.created_at, id=row.id)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    add_arguments(parser)
    parser.add_argument("--depth", type=int, default=1_000_000, help="rows before the deep page")
    args = parser.parse_args(argv)
    explain(lambda session: build_scenarios(session, args.depth), runs=args.runs, only=args.only)


if __name__ == "__main__":
    main()
