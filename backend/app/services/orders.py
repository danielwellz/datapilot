"""Reading orders: a filtered list with keyset pagination, and one order in full."""

import dataclasses
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.errors import NotFound
from app.models import Order, OrderSort
from app.repositories.orders import Keyset, OrderFilters, OrderRepository
from app.schemas.orders import OrderListQuery
from app.services.cursors import CursorSigner, InvalidCursor

CURSOR_PURPOSE = "datapilot.orders-cursor"

_CENT = Decimal("0.01")


class _CursorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Bumped when the format changes, so older cursors fail validation.
    v: Literal[1] = 1
    id: int
    filters: str = Field(description="Fingerprint of the filters the cursor was issued for.")


class _CreatedAtCursor(_CursorPayload):
    sort: Literal[OrderSort.CREATED_AT]
    key: AwareDatetime


class _TotalCursor(_CursorPayload):
    sort: Literal[OrderSort.TOTAL]
    key: Decimal


_cursor_adapter: TypeAdapter[_CreatedAtCursor | _TotalCursor] = TypeAdapter(
    Annotated[_CreatedAtCursor | _TotalCursor, Field(discriminator="sort")]
)


class OrderNotFound(NotFound):
    default_message = "The order does not exist."


@dataclass(frozen=True, slots=True)
class OrderPage:
    orders: Sequence[Order]
    next_cursor: str | None


class OrderService:
    """Reads orders; the cursor secret signs and verifies pagination cursors."""

    def __init__(self, session: Session, cursor_secret: bytes) -> None:
        self._orders = OrderRepository(session)
        self._cursors = CursorSigner(cursor_secret, CURSOR_PURPOSE)

    def list_orders(self, query: OrderListQuery) -> OrderPage:
        """One page of matching orders, newest (or largest) first.

        Raises ``InvalidCursor`` when the cursor was not issued by this
        server or was issued for a different sort or set of filters.
        """
        filters = filters_from_query(query)
        fingerprint = _fingerprint(filters)
        after = None
        if query.cursor is not None:
            after = self._read_cursor(query.cursor, query.sort, fingerprint)
        # One row more than the page: if it comes back, a next page exists,
        # which is known without counting the matching rows.
        rows = self._orders.list_page(filters, query.sort, after, query.limit + 1)
        page = rows[: query.limit]
        next_cursor = None
        if len(rows) > query.limit:
            next_cursor = self._write_cursor(page[-1], query.sort, fingerprint)
        return OrderPage(orders=page, next_cursor=next_cursor)

    def get_order(self, order_id: int) -> Order:
        """The order with its customer and items, or raise ``OrderNotFound``."""
        order = self._orders.get_with_details(order_id)
        if order is None:
            raise OrderNotFound(details=[{"order_id": order_id}])
        return order

    def _write_cursor(self, last: Order, sort: OrderSort, fingerprint: str) -> str:
        key = last.created_at if sort is OrderSort.CREATED_AT else last.total
        payload = _cursor_adapter.validate_python(
            {"sort": sort, "key": key, "id": last.id, "filters": fingerprint}
        )
        return self._cursors.sign(_cursor_adapter.dump_json(payload))

    def _read_cursor(self, cursor: str, sort: OrderSort, fingerprint: str) -> Keyset:
        try:
            payload = _cursor_adapter.validate_json(self._cursors.unsign(cursor))
        except ValidationError as error:
            raise InvalidCursor() from error
        # A cursor marks a position in one particular ordering of one result
        # set; applied to another it would silently skip or repeat rows.
        if payload.sort != sort or payload.filters != fingerprint:
            raise InvalidCursor()
        return Keyset(value=payload.key, id=payload.id)


def filters_from_query(query: OrderListQuery) -> OrderFilters:
    """Translate request filters into query conditions.

    Calendar days become half-open UTC instants: ``date_to`` includes its
    whole day, up to but excluding midnight of the next. Statuses are
    deduplicated and sorted, and totals brought to two decimal places, so
    equivalent queries share a cursor fingerprint ("20" and "20.00" alike).
    """
    return OrderFilters(
        statuses=tuple(sorted(set(query.status))),
        country=query.country,
        customer_id=query.customer_id,
        channel=query.channel,
        created_from=None if query.date_from is None else _start_of_utc_day(query.date_from),
        created_before=None if query.date_to is None else _start_of_next_utc_day(query.date_to),
        min_total=None if query.min_total is None else _to_cents(query.min_total),
        max_total=None if query.max_total is None else _to_cents(query.max_total),
    )


def _to_cents(amount: Decimal) -> Decimal:
    # Exact: the query schema allows at most two decimal places.
    return amount.quantize(_CENT)


def _start_of_utc_day(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _start_of_next_utc_day(day: date) -> datetime | None:
    # No instant follows the last day Python can represent; it bounds nothing.
    if day == date.max:
        return None
    return _start_of_utc_day(day + timedelta(days=1))


def _fingerprint(filters: OrderFilters) -> str:
    canonical = json.dumps(dataclasses.asdict(filters), default=str, sort_keys=True)
    return hashlib.blake2b(canonical.encode(), digest_size=8).hexdigest()
