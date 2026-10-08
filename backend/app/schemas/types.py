"""Field types shared by request and response schemas."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    EmailStr,
    Field,
    PlainSerializer,
    StringConstraints,
    WithJsonSchema,
)

# The largest value of a PostgreSQL bigint, the type of every primary key.
MAX_DATABASE_ID = 2**63 - 1


def _to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        # Every column is timestamptz, so a naive value is a bug; guessing its
        # zone would silently shift the instant.
        raise ValueError("Refusing to serialize a naive datetime as UTC")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[
    datetime,
    # Pydantic writes "+00:00"; the API contract is ISO 8601 with a "Z" suffix.
    PlainSerializer(_to_utc_iso, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time", "examples": ["2026-09-30T12:00:00Z"]}),
]
"""An aware datetime, serialized in JSON as ISO 8601 UTC ("2026-09-30T12:00:00Z")."""

NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]
"""A syntactically valid email, lowercased so that comparisons ignore case.

Lowercasing the local part is technically lossy (RFC 5321 lets servers treat
it as case-sensitive), but no mainstream provider does, and treating
Ana@x.dev and ana@x.dev as two accounts would be far more surprising.
"""


def _to_money_string(value: Decimal) -> str:
    return f"{value:.2f}"


Money = Annotated[
    Decimal,
    # A JSON number would pass through a float in most clients and lose cents.
    PlainSerializer(_to_money_string, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["1234.50"]}),
]
"""An amount of money, serialized in JSON as a decimal string with two places ("1234.50")."""

DatabaseId = Annotated[int, Field(ge=1, le=MAX_DATABASE_ID)]
"""A primary key value in a request. Bounded, so an oversized number is a 422
rather than an out-of-range error from the database."""

CountryCode = Annotated[
    str,
    # The pattern runs before any case conversion, so it accepts both cases.
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{2}$"),
    AfterValidator(str.upper),
]
"""An ISO 3166-1 alpha-2 code in either case, normalized to uppercase."""
