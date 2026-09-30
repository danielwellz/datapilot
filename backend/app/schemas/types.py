"""Field types shared by request and response schemas."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, EmailStr, PlainSerializer, WithJsonSchema


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
