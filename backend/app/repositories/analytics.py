"""Runs the analytics SQL in ``app/analytics/sql`` with bound parameters."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import RowMapping
from sqlalchemy.orm import Session

from app.analytics import queries


@dataclass(frozen=True, slots=True)
class PeriodTotals:
    revenue: Decimal = Decimal(0)
    paid_orders: int = 0
    placed_orders: int = 0
    refunded_orders: int = 0
    active_customers: int = 0


class AnalyticsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def period_totals(
        self, *, previous_start: datetime, current_start: datetime, current_end: datetime
    ) -> tuple[PeriodTotals, PeriodTotals]:
        """Totals of the current and the previous period; zeros for a period without orders."""
        rows = self._session.execute(
            queries.SUMMARY,
            {
                "previous_start": previous_start,
                "current_start": current_start,
                "current_end": current_end,
            },
        ).mappings()
        by_period = {
            row["period"]: PeriodTotals(
                revenue=row["revenue"],
                paid_orders=row["paid_orders"],
                placed_orders=row["placed_orders"],
                refunded_orders=row["refunded_orders"],
                active_customers=row["active_customers"],
            )
            for row in rows
        }
        return by_period.get("current", PeriodTotals()), by_period.get("previous", PeriodTotals())

    def monthly_revenue(self, *, first_month: date, last_month: date) -> Sequence[RowMapping]:
        """One row per month, columns named as in ``MonthlyRevenueOut``."""
        return (
            self._session.execute(
                queries.REVENUE_MONTHLY, {"first_month": first_month, "last_month": last_month}
            )
            .mappings()
            .all()
        )

    def top_customers(
        self, *, start_at: datetime, end_at: datetime, country: str | None, limit: int
    ) -> Sequence[RowMapping]:
        """Ranked customers, columns named as in ``TopCustomerOut``."""
        return (
            self._session.execute(
                queries.TOP_CUSTOMERS,
                {"start_at": start_at, "end_at": end_at, "country": country, "limit": limit},
            )
            .mappings()
            .all()
        )
