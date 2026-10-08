"""Sales analytics endpoints for the dashboard, answered from the response cache."""

from collections.abc import Callable
from datetime import date

from flask import Blueprint
from flask import Response as FlaskResponse
from pydantic import BaseModel
from spectree import Response, Tag

from app import clock
from app.api.caching import CACHE_NOTE, cached_json
from app.api.security import BEARER_AUTH, require_access_token
from app.api.spec import spec
from app.extensions import db
from app.schemas.analytics import (
    CohortsOut,
    CohortsQuery,
    ProductRankingOut,
    ProductRankingQuery,
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

_TAGS = [
    Tag(
        name="analytics",
        description="Sales analytics over paid orders, in complete UTC days and months. "
        + CACHE_NOTE,
    )
]


def _service() -> AnalyticsService:
    return AnalyticsService(db.session())


def _cached(name: str, query: BaseModel, compute: Callable[[date], BaseModel]) -> FlaskResponse:
    # Periods end yesterday, so today's date is an input of every response
    # and part of its key: entries from yesterday are never served today.
    today = clock.utc_today()
    params = {**query.model_dump(mode="json"), "as_of": today.isoformat()}
    return cached_json(f"analytics:{name}", params, lambda: compute(today))


@analytics.get("/summary")
@spec.validate(
    query=SummaryQuery,
    resp=Response(HTTP_200=SummaryOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def summary(query: SummaryQuery) -> FlaskResponse:
    """Revenue, orders, average order value, active customers and refund rate.

    The period is the `days` complete UTC days ending yesterday; each number
    is compared with the period of equal length just before it. Only paid
    orders count as revenue.
    """
    return _cached("summary", query, lambda today: _service().summary(query, today=today))


@analytics.get("/revenue-monthly")
@spec.validate(
    query=RevenueMonthlyQuery,
    resp=Response(HTTP_200=RevenueMonthlyOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def revenue_monthly(query: RevenueMonthlyQuery) -> FlaskResponse:
    """Paid revenue and orders per month, with MoM and YoY change and a 3-month average.

    Covers the `months` complete UTC calendar months ending last month,
    oldest first. Months without sales are included with zero revenue.
    """
    return _cached(
        "revenue-monthly", query, lambda today: _service().revenue_monthly(query, today=today)
    )


@analytics.get("/top-customers")
@spec.validate(
    query=TopCustomersQuery,
    resp=Response(HTTP_200=TopCustomersOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def top_customers(query: TopCustomersQuery) -> FlaskResponse:
    """The best customers of each country by paid revenue over the last `days` days.

    Customers are ranked within their country with a dense rank: equal
    revenue shares a rank and the next rank follows without a gap. Every
    customer ranked `limit` or better is returned, so ties can make a
    country return more than `limit` customers.
    """
    return _cached(
        "top-customers", query, lambda today: _service().top_customers(query, today=today)
    )


@analytics.get("/products")
@spec.validate(
    query=ProductRankingQuery,
    resp=Response(HTTP_200=ProductRankingOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def product_ranking(query: ProductRankingQuery) -> FlaskResponse:
    """Products ranked by paid revenue over the last `days` days, with units sold.

    Each product also reports its share of its category's revenue, computed
    over the whole category, not only the products returned. With
    `category`, products are ranked within that category. Ties share a rank.
    """
    return _cached("products", query, lambda today: _service().product_ranking(query, today=today))


@analytics.get("/cohorts")
@spec.validate(
    query=CohortsQuery,
    resp=Response(HTTP_200=CohortsOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def cohorts(query: CohortsQuery) -> FlaskResponse:
    """Customer retention by signup month.

    Customers who signed up in the same UTC month form a cohort. For each
    month since signup, up to last month, the share of the cohort that
    placed at least one paid order. Covers the `months` cohorts ending
    last month.
    """
    return _cached("cohorts", query, lambda today: _service().cohorts(query, today=today))
