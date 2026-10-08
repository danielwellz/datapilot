"""Orders and the products each one contains."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.product import Product


class OrderStatus(StrEnum):
    PAID = "paid"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class OrderChannel(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    MARKETPLACE = "marketplace"


class OrderSort(StrEnum):
    """Orderings the orders list offers, each descending with ``id`` breaking ties."""

    CREATED_AT = "created_at"
    TOTAL = "total"


def _one_of(column: str, values: type[StrEnum]) -> str:
    """SQL for a check that ``column`` holds one of the enum's values.

    Built from the enum so Python and the database list the same values. The
    input is a class defined in this module, never user data.
    """
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(_one_of("status", OrderStatus), name="status_allowed"),
        CheckConstraint(_one_of("channel", OrderChannel), name="channel_allowed"),
        CheckConstraint("total >= 0", name="total_non_negative"),
        # One per query shape of the orders list, each ending in id for keyset
        # pagination; docs/performance.md shows the plans that use them.
        Index("ix_orders_created_at_id", "created_at", "id"),
        Index("ix_orders_total_id", "total", "id"),
        Index("ix_orders_customer_id_created_at_id", "customer_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    # Plain text with a check rather than a native enum type: adding a value
    # later is a constraint swap, not an ALTER TYPE on a large table.
    status: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime]

    customer: Mapped[Customer] = relationship(back_populates="orders", lazy="raise")
    # Product order is arbitrary but fixed, and matches the primary key, so
    # loading the items needs no sort beyond the index scan.
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", lazy="raise", order_by="OrderItem.product_id"
    )

    def __repr__(self) -> str:
        return f"Order(id={self.id!r}, status={self.status!r}, total={self.total!r})"


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
    )

    # Items are part of their order and go with it; a product that was ever
    # sold cannot be deleted out from under its order history.
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)
    # The price paid, copied at order time: catalog prices change later.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped[Order] = relationship(back_populates="items", lazy="raise")
    product: Mapped[Product] = relationship(lazy="raise")

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    def __repr__(self) -> str:
        return f"OrderItem(order_id={self.order_id!r}, product_id={self.product_id!r})"
