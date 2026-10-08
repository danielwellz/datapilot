"""Filter options for the orders explorer."""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models import OrderChannel, OrderStatus
from app.repositories.meta import MetaRepository
from app.schemas.meta import MetaOut


def _utc_date(instant: datetime | None) -> date | None:
    # Date filters are UTC calendar days, so the bounds must be too, whatever
    # time zone the database session reports timestamps in.
    return None if instant is None else instant.astimezone(UTC).date()


class MetaService:
    def __init__(self, session: Session) -> None:
        self._meta = MetaRepository(session)

    def filter_options(self) -> MetaOut:
        first, last = self._meta.order_time_bounds()
        return MetaOut(
            countries=list(self._meta.countries()),
            statuses=list(OrderStatus),
            channels=list(OrderChannel),
            categories=list(self._meta.categories()),
            first_order_date=_utc_date(first),
            last_order_date=_utc_date(last),
        )
