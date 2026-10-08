"""Sales analytics: turns periods into query bounds and query rows into responses."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.repositories.analytics import AnalyticsRepository, PeriodTotals
from app.schemas.analytics import (
    CountMetricOut,
    MoneyMetricOut,
    MonthlyRevenueOut,
    PeriodOut,
    ProductRankingOut,
    ProductRankingQuery,
    ProductRankOut,
    RateMetricOut,
    RevenueMonthlyOut,
    RevenueMonthlyQuery,
    SummaryOut,
    SummaryQuery,
    TopCustomerOut,
    TopCustomersOut,
    TopCustomersQuery,
)
from app.services.periods import DayRange, preceding_days, trailing_days, trailing_months

_CENT = Decimal("0.01")
# Matches round(x, 4) in the SQL files: half away from zero, four places.
_RATIO_PLACES = Decimal("0.0001")


def change(current: Decimal | int | None, previous: Decimal | int | None) -> Decimal | None:
    """Relative change from ``previous`` to ``current``; None without a non-zero baseline."""
    if current is None or previous is None or previous == 0:
        return None
    return _round(_exact_ratio(current - previous, previous), _RATIO_PLACES)


class AnalyticsService:
    def __init__(self, session: Session) -> None:
        self._analytics = AnalyticsRepository(session)

    def summary(self, query: SummaryQuery, *, today: date) -> SummaryOut:
        """KPIs of the ``query.days`` days before ``today``, against the days before those."""
        period = trailing_days(today, query.days)
        previous_period = preceding_days(period)
        current, previous = self._analytics.period_totals(
            previous_start=previous_period.start_at,
            current_start=period.start_at,
            current_end=period.end_at,
        )
        # Changes are computed from unrounded values, so rounding the shown
        # average or rate never shifts the change.
        average, previous_average = _average_order_value(current), _average_order_value(previous)
        rate, previous_rate = _refund_rate(current), _refund_rate(previous)
        return SummaryOut(
            period=_period_out(period),
            previous_period=_period_out(previous_period),
            revenue=MoneyMetricOut(
                current=current.revenue,
                previous=previous.revenue,
                change=change(current.revenue, previous.revenue),
            ),
            orders=CountMetricOut(
                current=current.paid_orders,
                previous=previous.paid_orders,
                change=change(current.paid_orders, previous.paid_orders),
            ),
            average_order_value=MoneyMetricOut(
                current=_round(average, _CENT),
                previous=_round(previous_average, _CENT),
                change=change(average, previous_average),
            ),
            active_customers=CountMetricOut(
                current=current.active_customers,
                previous=previous.active_customers,
                change=change(current.active_customers, previous.active_customers),
            ),
            refund_rate=RateMetricOut(
                current=_round(rate, _RATIO_PLACES),
                previous=_round(previous_rate, _RATIO_PLACES),
                change=change(rate, previous_rate),
            ),
        )

    def revenue_monthly(self, query: RevenueMonthlyQuery, *, today: date) -> RevenueMonthlyOut:
        """Revenue of the ``query.months`` complete months before the month of ``today``."""
        period = trailing_months(today, query.months)
        rows = self._analytics.monthly_revenue(
            first_month=period.first_month, last_month=period.last_month
        )
        return RevenueMonthlyOut(
            items=[MonthlyRevenueOut.model_validate(dict(row)) for row in rows]
        )

    def top_customers(self, query: TopCustomersQuery, *, today: date) -> TopCustomersOut:
        """Customers ranked by paid revenue within each country over the last ``query.days``."""
        period = trailing_days(today, query.days)
        rows = self._analytics.top_customers(
            start_at=period.start_at,
            end_at=period.end_at,
            country=query.country,
            limit=query.limit,
        )
        return TopCustomersOut(items=[TopCustomerOut.model_validate(dict(row)) for row in rows])

    def product_ranking(self, query: ProductRankingQuery, *, today: date) -> ProductRankingOut:
        """Products ranked by paid revenue over the last ``query.days`` days."""
        period = trailing_days(today, query.days)
        rows = self._analytics.product_ranking(
            start_at=period.start_at,
            end_at=period.end_at,
            category=query.category,
            limit=query.limit,
        )
        return ProductRankingOut(items=[ProductRankOut.model_validate(dict(row)) for row in rows])


def _average_order_value(totals: PeriodTotals) -> Decimal | None:
    if totals.paid_orders == 0:
        return None
    return _exact_ratio(totals.revenue, totals.paid_orders)


def _refund_rate(totals: PeriodTotals) -> Decimal | None:
    if totals.placed_orders == 0:
        return None
    return _exact_ratio(totals.refunded_orders, totals.placed_orders)


def _exact_ratio(numerator: Decimal | int, denominator: Decimal | int) -> Decimal:
    return Decimal(numerator) / Decimal(denominator)


def _round(value: Decimal | None, places: Decimal) -> Decimal | None:
    return None if value is None else value.quantize(places, ROUND_HALF_UP)


def _period_out(period: DayRange) -> PeriodOut:
    return PeriodOut(start_date=period.first_day, end_date=period.last_day)
