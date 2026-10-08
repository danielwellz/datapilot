"""Customers who place orders in the analysed store."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, BigInteger, CheckConstraint, Identity, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base
from app.models.user import EMAIL_MAX_LENGTH

if TYPE_CHECKING:
    from app.models.order import Order

CUSTOMER_NAME_MAX_LENGTH = 100


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        # ISO 3166-1 alpha-2, uppercase: filters and group-bys compare codes
        # as plain strings, so "us" and "US" must never both exist.
        CheckConstraint("country ~ '^[A-Z]{2}$'", name="country_iso_alpha2"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(CUSTOMER_NAME_MAX_LENGTH))
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    country: Mapped[str] = mapped_column(CHAR(2))
    signed_up_at: Mapped[datetime]

    # "raise" turns an accidental lazy load into an error instead of a
    # silent extra query per row; API code loads relationships explicitly.
    orders: Mapped[list[Order]] = relationship(back_populates="customer", lazy="raise")

    def __repr__(self) -> str:
        return f"Customer(id={self.id!r}, country={self.country!r})"
