"""Sales analytics endpoints for the dashboard."""

from flask import Blueprint
from spectree import Response

from app import clock
from app.api.security import BEARER_AUTH, require_access_token
from app.api.spec import spec
from app.extensions import db
from app.schemas.analytics import (
    RevenueMonthlyOut,
    RevenueMonthlyQuery,
    SummaryOut,
    SummaryQuery,
    TopCustomersOut,
    TopCustomersQuery,
)
from app.schemas.errors import ErrorOut
from app.services.analytics import AnalyticsService

analytics = Blueprint("analytics", __name__, url_prefix="/analytics")

_TAGS = ["analytics"]


def _service() -> AnalyticsService:
    return AnalyticsService(db.session())


@analytics.get("/summary")
@spec.validate(
    query=SummaryQuery,
    resp=Response(HTTP_200=SummaryOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def summary(query: SummaryQuery) -> SummaryOut:
    """Revenue, orders, average order value, active customers and refund rate.

    The period is the `days` complete UTC days ending yesterday; each number
    is compared with the period of equal length just before it. Only paid
    orders count as revenue.
    """
    return _service().summary(query, today=clock.utc_today())


@analytics.get("/revenue-monthly")
@spec.validate(
    query=RevenueMonthlyQuery,
    resp=Response(HTTP_200=RevenueMonthlyOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def revenue_monthly(query: RevenueMonthlyQuery) -> RevenueMonthlyOut:
    """Paid revenue and orders per month, with MoM and YoY change and a 3-month average.

    Covers the `months` complete UTC calendar months ending last month,
    oldest first. Months without sales are included with zero revenue.
    """
    return _service().revenue_monthly(query, today=clock.utc_today())


@analytics.get("/top-customers")
@spec.validate(
    query=TopCustomersQuery,
    resp=Response(HTTP_200=TopCustomersOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def top_customers(query: TopCustomersQuery) -> TopCustomersOut:
    """The best customers of each country by paid revenue over the last `days` days.

    Customers are ranked within their country with a dense rank: equal
    revenue shares a rank and the next rank follows without a gap. Every
    customer ranked `limit` or better is returned, so ties can make a
    country return more than `limit` customers.
    """
    return _service().top_customers(query, today=clock.utc_today())
