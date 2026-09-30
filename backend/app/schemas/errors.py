"""The error envelope every failed request returns."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.types import JsonValue


class ErrorBody(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(description="Stable, machine-readable error code, e.g. `not_found`.")
    message: str = Field(description="Human-readable explanation, safe to show to users.")
    details: list[dict[str, JsonValue]] = Field(
        default_factory=list,
        description="Structured specifics, such as one entry per invalid field.",
    )
    request_id: str = Field(description="Matches the X-Request-ID response header.")


class ErrorOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    error: ErrorBody
