"""Errors of Ask your data, each rendered through the standard error envelope."""

from http import HTTPStatus

from app.errors import AppError


class ModelNotAvailable(AppError):
    status = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "model_not_available"
    default_message = "The requested model is not available."
