"""Application errors and the handlers that render every failure as JSON.

Whatever goes wrong, and wherever it happens, the client receives the same
envelope: ``{"error": {"code", "message", "details", "request_id"}}``.
"""

import logging
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import ClassVar

from flask import Flask, Response, jsonify
from pydantic import ValidationError
from pydantic.types import JsonValue
from werkzeug.exceptions import HTTPException

from app.logging import get_request_id
from app.schemas.errors import ErrorBody, ErrorOut

logger = logging.getLogger(__name__)

ErrorDetails = Sequence[Mapping[str, JsonValue]]

# Codes for errors raised by Flask and Werkzeug rather than by our code. Spelled
# out because clients match on them, and HTTPStatus phrases change between
# Python versions (422 became "Unprocessable Content" in 3.13).
_HTTP_ERROR_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_failed",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


class AppError(Exception):
    """Base class for errors that map to a specific HTTP response.

    Subclasses set ``status``, ``code`` and a default ``message``; callers
    may override the message and attach structured ``details``.
    """

    status: ClassVar[int] = HTTPStatus.INTERNAL_SERVER_ERROR
    code: ClassVar[str] = "internal_error"
    default_message: ClassVar[str] = "The server could not complete the request."

    def __init__(self, message: str | None = None, *, details: ErrorDetails = ()) -> None:
        self.message = message or self.default_message
        self.details = [dict(detail) for detail in details]
        super().__init__(self.message)

    @property
    def headers(self) -> dict[str, str]:
        return {}


class BadRequest(AppError):
    status = HTTPStatus.BAD_REQUEST
    code = "bad_request"
    default_message = "The request is malformed."


class Unauthorized(AppError):
    status = HTTPStatus.UNAUTHORIZED
    code = "unauthorized"
    default_message = "Authentication is required."


class Forbidden(AppError):
    status = HTTPStatus.FORBIDDEN
    code = "forbidden"
    default_message = "You do not have permission to perform this action."


class NotFound(AppError):
    status = HTTPStatus.NOT_FOUND
    code = "not_found"
    default_message = "The requested resource does not exist."


class Conflict(AppError):
    status = HTTPStatus.CONFLICT
    code = "conflict"
    default_message = "The request conflicts with the current state of the resource."


class UnsupportedMediaType(AppError):
    status = HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_media_type"
    default_message = "The request body is in an unsupported format."


class ValidationFailed(AppError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "validation_failed"
    default_message = "The request contains invalid data."

    @classmethod
    def from_pydantic(cls, error: ValidationError) -> "ValidationFailed":
        """Describe each invalid field without echoing the submitted value.

        Pydantic includes the offending input by default, which could send a
        password or token straight back to the client and into logs.
        """
        details: list[dict[str, JsonValue]] = [
            {"loc": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors(include_url=False, include_input=False, include_context=False)
        ]
        return cls(details=details)


class RateLimited(AppError):
    status = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"
    default_message = "Too many requests. Try again later."

    def __init__(
        self, retry_after_seconds: int, message: str | None = None, *, details: ErrorDetails = ()
    ) -> None:
        super().__init__(message, details=details)
        self.retry_after_seconds = retry_after_seconds

    @property
    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after_seconds)}


class ServiceUnavailable(AppError):
    status = HTTPStatus.SERVICE_UNAVAILABLE
    code = "service_unavailable"
    default_message = "The service is temporarily unavailable."


def error_response(
    status: int,
    code: str,
    message: str,
    details: ErrorDetails = (),
    headers: Mapping[str, str] | None = None,
) -> Response:
    """Render the standard error envelope."""
    body = ErrorOut(
        error=ErrorBody(
            code=code,
            message=message,
            details=[dict(detail) for detail in details],
            request_id=get_request_id(),
        )
    )
    response = jsonify(body.model_dump(mode="json"))
    response.status_code = status
    response.headers.update(headers or {})
    return response


def register_error_handlers(app: Flask) -> None:
    """Install the handlers; Flask picks the most specific one for each exception."""
    # A raw pydantic ValidationError deliberately has no handler of its own:
    # client input is converted to ValidationFailed (422) where it is parsed,
    # so one that escapes from our code is a server bug and becomes a 500.
    app.register_error_handler(AppError, _handle_app_error)
    app.register_error_handler(HTTPException, _handle_http_exception)
    app.register_error_handler(Exception, _handle_unexpected_error)


def _handle_app_error(error: AppError) -> Response:
    return error_response(error.status, error.code, error.message, error.details, error.headers)


def _handle_http_exception(error: HTTPException) -> Response:
    # Routing and framework errors (404, 405, 415, ...). Werkzeug's descriptions
    # are generic, public text; its headers matter (405 must list Allow).
    status = error.code or HTTPStatus.INTERNAL_SERVER_ERROR
    headers = {name: value for name, value in error.get_headers() if name.lower() != "content-type"}
    code = _HTTP_ERROR_CODES.get(status, "http_error")
    return error_response(status, code, error.description or error.name, (), headers)


def _handle_unexpected_error(error: Exception) -> Response:
    # The traceback goes to the logs only; the client gets the request id to quote.
    logger.exception("unhandled exception", exc_info=error)
    return error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "internal_error",
        "An unexpected error occurred. Quote the request id when reporting it.",
    )
