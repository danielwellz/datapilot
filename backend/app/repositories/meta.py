"""Queries behind the filter options of the orders explorer."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Customer, Order, Product


class MetaRepository:
    """Distinct values and ranges that filter controls offer."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def countries(self) -> Sequence[str]:
        return self._session.scalars(
            select(Customer.country).distinct().order_by(Customer.country)
        ).all()

    def categories(self) -> Sequence[str]:
        return self._session.scalars(
            select(Product.category).distinct().order_by(Product.category)
        ).all()

    def order_time_bounds(self) -> tuple[datetime | None, datetime | None]:
        """The first and last ``created_at``, or ``(None, None)`` without orders."""
        first, last = self._session.execute(
            select(func.min(Order.created_at), func.max(Order.created_at))
        ).one()
        return first, last
