"""Request validation and OpenAPI generation, provided by spectree.

Endpoints opt in with ``@spec.validate(...)`` and receive their validated
Pydantic models as ``query`` and ``json`` arguments. Only decorated
endpoints appear in the OpenAPI document (``mode="strict"``).

spectree's own error responses are replaced: its hooks raise instead, so
every failure is rendered by ``app.errors`` in the standard envelope.
"""

from typing import Any

from pydantic import BaseModel, ValidationError
from spectree import SecurityScheme, SecuritySchemeData, SpecTree
from spectree.models import InType, SecureType

from app.errors import ValidationFailed
from app.schemas.errors import ErrorOut

API_TITLE = "DataPilot API"
API_VERSION = "0.1.0"


def _raise_request_validation_error(
    request: Any, response: Any, error: Exception | None, instance: Any, adapter: Any
) -> None:
    if isinstance(error, ValidationError):
        raise ValidationFailed.from_pydantic(error)
    if error is not None:
        raise error


def _raise_response_validation_error(
    request: Any, response: Any, error: Exception | None, instance: Any, adapter: Any
) -> None:
    # A response that breaks its own schema is a server bug. spectree would
    # answer 500 with the offending data in the body; raising sends it to the
    # generic handler instead, which logs it and reveals nothing.
    if error is not None:
        raise RuntimeError("Response does not match its declared schema") from error


def _model_name(model: type[BaseModel]) -> str:
    # spectree appends a hash of the module path by default; plain class
    # names keep the document readable, so schema names must stay unique.
    return model.__name__


spec = SpecTree(
    "flask",
    mode="strict",
    title=API_TITLE,
    version=API_VERSION,
    description="Sales analytics and natural-language questions over PostgreSQL.",
    before=_raise_request_validation_error,
    after=_raise_response_validation_error,
    validation_error_model=ErrorOut,
    naming_strategy=_model_name,
    security_schemes=[
        SecurityScheme(
            name="bearerAuth",
            data=SecuritySchemeData(
                type=SecureType.HTTP,
                scheme="bearer",
                bearer_format="JWT",
                description="Access token from login or refresh, valid for 15 minutes.",
            ),
        ),
        SecurityScheme(
            name="refreshCookie",
            data=SecuritySchemeData(
                type=SecureType.API_KEY,
                name="refresh_token_cookie",
                field_in=InType.COOKIE,
                description="Refresh token, set by login and refresh (httpOnly, path /api/auth).",
            ),
        ),
        SecurityScheme(
            name="csrfHeader",
            data=SecuritySchemeData(
                type=SecureType.API_KEY,
                name="X-CSRF-TOKEN",
                field_in=InType.HEADER,
                description="The value of the csrf_refresh_token cookie (double-submit).",
            ),
        ),
    ],
)
