"""Measure the query plans of the analytics endpoints with EXPLAIN (ANALYZE, BUFFERS).

Each scenario calls the analytics service exactly as the API does on a cache
miss; ``scripts.plans`` records its SQL and explains it with the real
parameters. Scenarios cover each endpoint's default and widest parameters,
since the widest periods read the most rows.

Usage, from ``backend/`` against the database in ``DATABASE_URL``::

    uv run python -m scripts.explain_analytics [--runs 10] [--as-of 2026-10-08] [--only NAME ...]
"""

import argparse
from collections.abc import Sequence
from datetime import date

from sqlalchemy.orm import Session

from app.clock import utc_today
from app.schemas.analytics import (
    MAX_COHORT_MONTHS,
    MAX_DAYS,
    MAX_REVENUE_MONTHS,
    CohortsQuery,
    ProductRankingQuery,
    RevenueMonthlyQuery,
    SummaryQuery,
    TopCustomersQuery,
)
from app.services.analytics import AnalyticsService
from scripts.plans import Scenario, add_arguments, explain


def build_scenarios(session: Session, today: date) -> list[Scenario]:
    """One scenario per endpoint at its defaults, plus the widest period it accepts."""
    service = AnalyticsService(session)
    return [
        Scenario(
            "summary-30",
            "Summary of the last 30 days (default)",
            lambda: service.summary(SummaryQuery(), today=today),
        ),
        Scenario(
            "summary-365",
            f"Summary of the last {MAX_DAYS} days (widest)",
            lambda: service.summary(SummaryQuery(days=MAX_DAYS), today=today),
        ),
        Scenario(
            "revenue-monthly-24",
            "Monthly revenue, 24 months (default)",
            lambda: service.revenue_monthly(RevenueMonthlyQuery(), today=today),
        ),
        Scenario(
            "revenue-monthly-36",
            f"Monthly revenue, {MAX_REVENUE_MONTHS} months (widest)",
            lambda: service.revenue_monthly(
                RevenueMonthlyQuery(months=MAX_REVENUE_MONTHS), today=today
            ),
        ),
        Scenario(
            "top-customers",
            "Top 10 customers of every country, 365 days (default)",
            lambda: service.top_customers(TopCustomersQuery(), today=today),
        ),
        Scenario(
            "top-customers-de",
            "Top 10 customers in DE, 365 days",
            lambda: service.top_customers(TopCustomersQuery(country="DE"), today=today),
        ),
        Scenario(
            "products",
            "Top 20 products, 365 days (default)",
            lambda: service.product_ranking(ProductRankingQuery(), today=today),
        ),
        Scenario(
            "products-category",
            "Top 20 products in Electronics, 365 days",
            lambda: service.product_ranking(
                ProductRankingQuery(category="Electronics"), today=today
            ),
        ),
        Scenario(
            "cohorts-12",
            "Retention of 12 monthly cohorts (default)",
            lambda: service.cohorts(CohortsQuery(), today=today),
        ),
        Scenario(
            "cohorts-24",
            f"Retention of {MAX_COHORT_MONTHS} monthly cohorts (widest)",
            lambda: service.cohorts(CohortsQuery(months=MAX_COHORT_MONTHS), today=today),
        ),
    ]


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    add_arguments(parser)
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="the date the periods end before  [default: today (UTC)]",
    )
    args = parser.parse_args(argv)
    today = args.as_of or utc_today()
    explain(lambda session: build_scenarios(session, today), runs=args.runs, only=args.only)


if __name__ == "__main__":
    main()
