"""Orders explorer endpoints."""

from flask import Blueprint
from spectree import Response

from app.api.security import BEARER_AUTH, require_access_token
from app.api.spec import spec
from app.config import current_settings
from app.extensions import db
from app.schemas.errors import ErrorOut
from app.schemas.orders import OrderListQuery, OrderPageOut, OrderSummaryOut
from app.services.orders import OrderService

orders = Blueprint("orders", __name__)


def _order_service() -> OrderService:
    secret = current_settings().secret_key.get_secret_value().encode()
    return OrderService(db.session(), cursor_secret=secret)


@orders.get("/orders")
@spec.validate(
    query=OrderListQuery,
    resp=Response(HTTP_200=OrderPageOut, HTTP_400=ErrorOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=["orders"],
    security=BEARER_AUTH,
)
@require_access_token
def list_orders(query: OrderListQuery) -> OrderPageOut:
    """List orders, newest first or by total, with filters and cursor pagination.

    Follow `next_cursor` with the same filters and sort to get the next page;
    it stays fast at any depth. A cursor that was edited, or that belongs to
    other filters or another sort, answers 400 `invalid_cursor`. Every filter
    is optional, and filters combine with AND.
    """
    page = _order_service().list_orders(query)
    return OrderPageOut(
        items=[OrderSummaryOut.model_validate(order) for order in page.orders],
        next_cursor=page.next_cursor,
    )
