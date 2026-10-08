"""Errors of Ask your data, each rendered through the standard error envelope.

Every error raised after a question was audited carries one detail object
with the audit id, the models involved and the SQL (when there was some), so
the client can still show a receipt of what happened. The SQL in a detail is
model output: clients must display it as text.
"""

from http import HTTPStatus

from pydantic import JsonValue

from app.errors import AppError, ErrorDetails


def receipt(
    *,
    audit_id: int,
    requested_model: str,
    model: str | None,
    provider: str | None,
    sql: str | None = None,
    **extra: JsonValue,
) -> ErrorDetails:
    """The single error detail that lets a client show what happened to a question."""
    detail: dict[str, JsonValue] = {
        "audit_id": audit_id,
        "requested_model": requested_model,
        "model": model,
        "provider": provider,
        "sql": sql,
    }
    return [detail | extra]


class ModelNotAvailable(AppError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "model_not_available"
    default_message = "The requested model is not available."


class SqlRejected(AppError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "sql_rejected"
    default_message = "The generated query was not safe to run, so it was not run."


class QuestionUnanswerable(AppError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "question_unanswerable"
    default_message = "The sales data cannot answer this question."


class QueryTimeout(AppError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "query_timeout"
    default_message = "The query took too long and was stopped."


class QueryFailed(AppError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "query_failed"
    default_message = "The database could not run the generated query, even after a correction."


class LlmInvalidOutput(AppError):
    status = HTTPStatus.BAD_GATEWAY
    code = "llm_invalid_output"
    default_message = "The model did not return a usable answer. Try again or pick another model."


class LlmUnavailable(AppError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    code = "llm_unavailable"
    default_message = "No model could answer right now. Try again shortly or pick another model."


class LlmRateLimited(AppError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    code = "llm_rate_limited"
    default_message = (
        "The model's provider is rate limiting requests. Pick another model or try later."
    )

    def __init__(
        self,
        retry_after_seconds: int | None,
        message: str | None = None,
        *,
        details: ErrorDetails = (),
    ) -> None:
        super().__init__(message, details=details)
        self.retry_after_seconds = retry_after_seconds

    @property
    def headers(self) -> dict[str, str]:
        if self.retry_after_seconds is None:
            return {}
        return {"Retry-After": str(self.retry_after_seconds)}
