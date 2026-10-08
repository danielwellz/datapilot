"""The structured answer a model must give, and how it is read from free text.

Models are asked for a JSON object in their reply rather than through tool
calling, which not every provider or model supports in the same way. Replies
come back in many shapes (bare JSON, a fenced code block, prose around it,
a <think> block first), so the object is extracted, then validated with
Pydantic. Everything in it is untrusted: the SQL still goes through the guard,
and the text fields are bounded and shown as plain text.
"""

import json
import re
from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from app.ai.sql_guard import MAX_SQL_LENGTH

ChartKind = Literal["none", "bar", "line"]

MAX_EXPLANATION_LENGTH = 600
MAX_ASSUMPTIONS = 5
MAX_ASSUMPTION_LENGTH = 200

_ANSWER_KEYS = frozenset({"sql", "explanation", "chart", "assumptions"})
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

Assumption = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ASSUMPTION_LENGTH)
]


class LLMAnswer(BaseModel):
    """What the model must return for a question."""

    # Unknown keys are dropped rather than refused: they are harmless, and a
    # model adding one should not cost a retry.
    model_config = ConfigDict(extra="ignore", frozen=True)

    # None when the question cannot be answered from the data.
    sql: str | None = Field(max_length=MAX_SQL_LENGTH)
    explanation: str = Field(min_length=1, max_length=MAX_EXPLANATION_LENGTH)
    chart: ChartKind
    assumptions: list[Assumption] = Field(default_factory=list, max_length=MAX_ASSUMPTIONS)

    @field_validator("sql", mode="before")
    @classmethod
    def _blank_sql_means_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("explanation", mode="before")
    @classmethod
    def _strip_explanation(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


# The same contract as LLMAnswer, as a JSON schema for providers that can
# constrain their output to one. Written out rather than generated so it
# stays within what strict modes accept: every property required, no
# additional properties.
ANSWER_JSON_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "sql": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "explanation": {"type": "string"},
        "chart": {"type": "string", "enum": ["none", "bar", "line"]},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sql", "explanation", "chart", "assumptions"],
    "additionalProperties": False,
}


class InvalidAnswerError(ValueError):
    """The reply holds no valid answer. The message is written for the model to fix it."""


def parse_answer(text: str) -> LLMAnswer:
    """Extract and validate the answer object in a model's reply."""
    data = _answer_object(_THINK_BLOCK.sub("", text))
    try:
        return LLMAnswer.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or 'answer'}: {item['msg']}"
            for item in error.errors(include_url=False, include_input=False)
        )
        raise InvalidAnswerError(f"The JSON object is not a valid answer: {problems}.") from error


def _answer_object(text: str) -> dict[str, Any]:
    """The first JSON object in ``text`` that looks like an answer.

    Reasoning text before the answer can contain other JSON (an example, a
    sketch of the result), so objects without any answer key are skipped.
    """
    decoder = json.JSONDecoder()
    position = text.find("{")
    while position != -1:
        try:
            value, _ = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict) and _ANSWER_KEYS & value.keys():
            return value
        position = text.find("{", position + 1)
    raise InvalidAnswerError("The reply does not contain the JSON answer object.")
