"""Builders for test data, created inside the current test's transaction.

Plain typed functions rather than factory_boy: its declarations are not
annotated, so under ``mypy --strict`` every factory call would need an
exception and every test would get ``Any`` back.
"""

import itertools
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache

from app.extensions import db
from app.models import (
    Customer,
    Order,
    OrderChannel,
    OrderItem,
    OrderStatus,
    Product,
    User,
)
from app.services.passwords import PasswordHasher

DEFAULT_PASSWORD = "factory-password-2026"

_sequence = itertools.count(1)


@cache
def default_password_hash() -> str:
    # argon2 is slow on purpose; one hash shared by every built user keeps the
    # suite fast. It uses the production parameters, so logging in with it
    # does not trigger a rehash.
    return PasswordHasher().hash(DEFAULT_PASSWORD)


def build_user(
    *,
    email: str | None = None,
    full_name: str = "Ana Lima",
    password_hash: str | None = None,
) -> User:
    """Build an unsaved user; each call gets a unique email unless one is given."""
    return User(
        email=email or f"analyst{next(_sequence)}@datapilot.dev",
        full_name=full_name,
        password_hash=password_hash or default_password_hash(),
    )


def create_user(
    *,
    email: str | None = None,
    full_name: str = "Ana Lima",
    password_hash: str | None = None,
) -> User:
    """Insert and commit a user, as an earlier request would have.

    Committing matters: the session is removed whenever an app context ends,
    which discards anything only flushed. In the test harness the commit only
    releases a savepoint, so the row still disappears with the test.
    """
    user = build_user(email=email, full_name=full_name, password_hash=password_hash)
    db.session.add(user)
    db.session.commit()
    return user


_SIGNUP_TIME = datetime(2025, 1, 15, 9, 30, tzinfo=UTC)
_ORDER_TIME = datetime(2025, 6, 1, 18, 0, tzinfo=UTC)


def create_customer(
    *,
    email: str | None = None,
    name: str = "Mia Novak",
    country: str = "US",
    signed_up_at: datetime = _SIGNUP_TIME,
) -> Customer:
    """Insert and commit a customer; each call gets a unique email unless one is given."""
    customer = Customer(
        name=name,
        email=email or f"customer{next(_sequence)}@example.com",
        country=country,
        signed_up_at=signed_up_at,
    )
    return _commit(customer)


def create_product(
    *, name: str = "Trail Water Bottle", category: str = "Sports", price: str = "19.90"
) -> Product:
    return _commit(Product(name=name, category=category, price=Decimal(price)))


def create_order(
    customer: Customer,
    lines: Sequence[tuple[Product, int]],
    *,
    status: OrderStatus = OrderStatus.PAID,
    channel: OrderChannel = OrderChannel.WEB,
    created_at: datetime = _ORDER_TIME,
) -> Order:
    """Insert and commit an order whose total is the sum of its lines at catalog price."""
    items = [
        OrderItem(product_id=product.id, quantity=quantity, unit_price=product.price)
        for product, quantity in lines
    ]
    order = Order(
        customer_id=customer.id,
        status=status,
        channel=channel,
        total=sum((item.unit_price * item.quantity for item in items), Decimal(0)),
        created_at=created_at,
        items=items,
    )
    return _commit(order)


def _commit[T](instance: T) -> T:
    db.session.add(instance)
    db.session.commit()
    return instance
