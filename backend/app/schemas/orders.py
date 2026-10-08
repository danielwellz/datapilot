"""Query string and response bodies of the orders endpoints."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.models import OrderChannel, OrderSort, OrderStatus
from app.schemas.types import DatabaseId, Money, UtcDatetime

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

CountryCode = Annotated[
    str,
    # The pattern runs before any case conversion, so it accepts both cases.
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{2}$"),
    AfterValidator(str.upper),
]
"""An ISO 3166-1 alpha-2 code in either case, normalized to uppercase."""

TotalBound = Annotated[
    Decimal,
    Field(ge=0, max_digits=12, decimal_places=2),
    # Pydantic documents a decimal as "number or a long regex"; clients send
    # the same decimal string the API returns for money.
    WithJsonSchema(
        {"type": "string", "pattern": r"^\d{1,10}(\.\d{1,2})?$", "examples": ["100.00"]}
    ),
]


class OrderListQuery(BaseModel):
    """Filters, sort and page of the orders list. Every filter is optional."""

    model_config = ConfigDict(extra="forbid")

    status: list[OrderStatus] = Field(
        default_factory=list, description="Repeat to match any of several statuses."
    )
    country: CountryCode | None = Field(default=None, description="The customer's country.")
    customer_id: DatabaseId | None = None
    channel: OrderChannel | None = None
    date_from: date | None = Field(default=None, description="First UTC day included.")
    date_to: date | None = Field(default=None, description="Last UTC day included.")
    min_total: TotalBound | None = Field(default=None, description="Inclusive.")
    max_total: TotalBound | None = Field(default=None, description="Inclusive.")
    sort: OrderSort = Field(
        default=OrderSort.CREATED_AT, description="Descending; ties are broken by id."
    )
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    cursor: str | None = Field(
        default=None,
        description="The `next_cursor` of the previous page, sent with the same filters and sort.",
    )

    @model_validator(mode="after")
    def _check_ranges(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise PydanticCustomError("date_range", "date_from must be on or before date_to.", {})
        if (
            self.min_total is not None
            and self.max_total is not None
            and self.min_total > self.max_total
        ):
            raise PydanticCustomError(
                "total_range", "min_total must be less than or equal to max_total.", {}
            )
        return self


class OrderCustomerOut(BaseModel):
    """The customer of an order, as shown in the list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    country: str


class OrderSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: OrderStatus
    channel: OrderChannel
    total: Money
    created_at: UtcDatetime
    customer: OrderCustomerOut


class OrderPageOut(BaseModel):
    items: list[OrderSummaryOut]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    country: str
    signed_up_at: UtcDatetime


class OrderItemProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product: OrderItemProductOut
    quantity: int
    unit_price: Money = Field(
        description="The price paid per unit, fixed when the order was placed."
    )
    line_total: Money = Field(description="`unit_price` times `quantity`.")


class OrderOut(BaseModel):
    """An order with its customer and items."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: OrderStatus
    channel: OrderChannel
    total: Money = Field(description="The sum of the items' line totals.")
    created_at: UtcDatetime
    customer: CustomerOut
    items: list[OrderItemOut]
