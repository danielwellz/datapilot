"""Response body of the metadata endpoint."""

from datetime import date

from pydantic import BaseModel, Field

from app.models import OrderChannel, OrderStatus


class MetaOut(BaseModel):
    """The values the orders filters accept, for building filter controls."""

    countries: list[str] = Field(description="ISO 3166-1 alpha-2 codes of customer countries.")
    statuses: list[OrderStatus]
    channels: list[OrderChannel]
    categories: list[str]
    first_order_date: date | None = Field(
        description="UTC date of the oldest order; null when there are no orders."
    )
    last_order_date: date | None = Field(
        description="UTC date of the newest order; null when there are no orders."
    )
