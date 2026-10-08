"""A pinned "today" and helpers for the hand-built analytics datasets.

Every analytics test builds a dataset small enough to compute the expected
numbers by hand, and writes that arithmetic next to its assertions.
"""

from datetime import UTC, date, datetime

import pytest

from app import clock
from app.models import Customer, Order, OrderStatus
from tests.factories import create_order, create_product

TODAY = date(2026, 3, 15)


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> date:
    monkeypatch.setattr(clock, "utc_today", lambda: TODAY)
    return TODAY


def at(day: str, clock: str = "12:00:00") -> datetime:
    """A UTC instant from ISO text: ``at("2026-03-14", "23:59:59")``."""
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=UTC)


def sale(
    customer: Customer,
    amount: str,
    created_at: datetime,
    status: OrderStatus = OrderStatus.PAID,
) -> Order:
    """One order of a single item whose total is ``amount``."""
    return create_order(
        customer, [(create_product(price=amount), 1)], status=status, created_at=created_at
    )
