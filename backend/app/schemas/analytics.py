"""Query strings and response bodies of the analytics endpoints.

Periods are complete UTC days or months ending before today, so a period
never contains a partial day and comparisons between periods are fair.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema

from app.schemas.types import Money

MAX_DAYS = 365
MAX_REVENUE_MONTHS = 36

Ratio = Annotated[
    Decimal,
    # A JSON number: ratios are not money, and charts consume them directly.
    PlainSerializer(float, return_type=float, when_used="json"),
    WithJsonSchema({"type": "number", "examples": [0.1234]}),
]
"""A fraction rounded to four places: 0.1234 is 12.34%."""

Change = Annotated[
    Ratio | None,
    Field(
        description="Relative change against the previous period: 0.25 is +25%. "
        "Null when the previous value is zero or unknown."
    ),
]


class SummaryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(
        default=30,
        ge=1,
        le=MAX_DAYS,
        description="Length of the period in whole UTC days, ending yesterday.",
    )


class RevenueMonthlyQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    months: int = Field(
        default=24,
        ge=1,
        le=MAX_REVENUE_MONTHS,
        description="Number of complete UTC calendar months, ending last month.",
    )


class PeriodOut(BaseModel):
    start_date: date = Field(description="First UTC day of the period.")
    end_date: date = Field(description="Last UTC day of the period, included.")


class MoneyMetricOut(BaseModel):
    current: Money | None = Field(description="Null only for an average over no orders.")
    previous: Money | None
    change: Change


class CountMetricOut(BaseModel):
    current: int
    previous: int
    change: Change


class RateMetricOut(BaseModel):
    current: Ratio | None = Field(description="Null when the period has no orders.")
    previous: Ratio | None
    change: Change


class SummaryOut(BaseModel):
    """Headline numbers of a period, each compared with the period just before it."""

    period: PeriodOut
    previous_period: PeriodOut
    revenue: MoneyMetricOut = Field(description="Total of paid orders.")
    orders: CountMetricOut = Field(description="Paid orders.")
    average_order_value: MoneyMetricOut = Field(description="Revenue divided by paid orders.")
    active_customers: CountMetricOut = Field(description="Customers with at least one paid order.")
    refund_rate: RateMetricOut = Field(
        description="Refunded orders divided by all orders placed, in any status."
    )


class MonthlyRevenueOut(BaseModel):
    month: date = Field(description="First day of the month.")
    revenue: Money = Field(description="Total of paid orders; 0.00 for a month without sales.")
    orders: int = Field(description="Paid orders.")
    revenue_change_mom: Change = Field(description="Change against the month before.")
    revenue_change_yoy: Change = Field(description="Change against the same month a year earlier.")
    revenue_moving_average_3m: Money = Field(
        description="Average revenue of this month and the two before it."
    )


class RevenueMonthlyOut(BaseModel):
    """Revenue per month, oldest first, with every month present."""

    items: list[MonthlyRevenueOut]
