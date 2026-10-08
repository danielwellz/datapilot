"""Request and response bodies of the Ask your data endpoints.

Every text field that came from a model (SQL, explanation, assumptions) is
model output: clients must display it as plain text, never as HTML.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from app.ai.answer import ChartKind
from app.ai.executor import ColumnType
from app.models import AiQueryStatus
from app.schemas.types import UtcDatetime

MIN_QUESTION_LENGTH = 3
MAX_QUESTION_LENGTH = 500
DEFAULT_HISTORY_PAGE_SIZE = 20
MAX_HISTORY_PAGE_SIZE = 50

Question = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=MIN_QUESTION_LENGTH, max_length=MAX_QUESTION_LENGTH
    ),
]
# The shape of a registry id; whether it names an enabled model is checked
# against the registry, never trusted from the client.
ModelId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9.:-]{0,63}$")]


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Question = Field(examples=["What was the monthly revenue over the last 12 months?"])
    model: ModelId | None = Field(
        default=None,
        description="An id from `GET /api/ai/models`; the default model when left out.",
    )


class AnsweredByOut(BaseModel):
    id: str
    label: str
    provider: str
    provider_label: str


class ResultColumnOut(BaseModel):
    name: str
    type: ColumnType = Field(description="A hint for formatting and charts.")


class AskOut(BaseModel):
    """An answer: the SQL that ran, what it shows, and its result."""

    id: int = Field(description="The audit id of this question.")
    question: str
    requested_model: str
    model: AnsweredByOut = Field(description="The model that answered, after any fallback.")
    fell_back: bool = Field(description="True when another model answered than the one asked.")
    sql: str = Field(description="The SQL that ran, after the safety checks rewrote it.")
    explanation: str
    chart: ChartKind = Field(description="The chart the model suggests for the result.")
    assumptions: list[str]
    columns: list[ResultColumnOut]
    rows: list[list[JsonValue]] = Field(
        description="Decimals are strings, instants ISO 8601 UTC, as elsewhere in the API."
    )
    row_count: int
    truncated: bool = Field(description="True when more rows matched than the row limit.")
    repaired: bool = Field(description="True when the first query failed and was corrected.")
    latency_ms: int
    prompt_version: str
    created_at: UtcDatetime


class ModelOut(BaseModel):
    id: str
    label: str
    provider: str
    provider_label: str
    default: bool


class ModelsOut(BaseModel):
    items: list[ModelOut] = Field(description="The models that can answer right now.")
    default_model: str


class ExampleOut(BaseModel):
    question: str


class ExamplesOut(BaseModel):
    items: list[ExampleOut]


class HistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=DEFAULT_HISTORY_PAGE_SIZE, ge=1, le=MAX_HISTORY_PAGE_SIZE)
    cursor: str | None = Field(default=None, description="The `next_cursor` of the previous page.")


class HistoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    status: AiQueryStatus
    error_code: str | None
    requested_model: str
    model: str | None = Field(description="The model that answered; null when none did.")
    provider: str | None
    sql: str | None = Field(
        validation_alias="shown_sql",
        description="The SQL that ran, or for a rejected question the SQL that was refused.",
    )
    explanation: str | None
    chart: ChartKind | None
    assumptions: list[str]
    row_count: int | None
    truncated: bool
    repaired: bool
    latency_ms: int
    created_at: UtcDatetime


class HistoryPageOut(BaseModel):
    items: list[HistoryItemOut]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )
