"""JSON logging to stdout, request ids and the access log."""

import logging
import re
import sys
import time
import uuid
from typing import IO, Any

from flask import Flask, Response, g, has_request_context, request
from pythonjsonlogger.json import JsonFormatter

REQUEST_ID_HEADER = "X-Request-ID"

# Client-supplied ids end up in every log line, so anything that could forge
# or break a line (newlines, quotes, very long values) is replaced.
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")

# Identifies the handler configure_logging installs, so it can be replaced.
STDOUT_HANDLER_NAME = "app.stdout"

# The model provider SDKs' HTTP client logs every request at INFO, which
# repeats what the ask service already logs about each attempt.
_QUIET_LOGGERS = ("httpx2", "httpcore2")

access_logger = logging.getLogger("app.access")


class RequestIdFilter(logging.Filter):
    """Attach the current request id (or ``None`` outside a request) to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() if has_request_context() else None
        return True


def build_log_handler(stream: IO[str]) -> logging.Handler:
    """Create a handler that writes one JSON object per line to ``stream``."""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        JsonFormatter(
            "{levelname}{name}{message}",
            style="{",
            rename_fields={"levelname": "level", "name": "logger"},
            timestamp=True,
        )
    )
    handler.addFilter(RequestIdFilter())
    return handler


def gunicorn_log_config(level: str) -> dict[str, Any]:
    """Gunicorn's ``logconfig_dict``: its master and workers log through the same JSON handler.

    The handler carries the name configure_logging uses, so the app replaces
    it in each worker instead of adding a second one.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            STDOUT_HANDLER_NAME: {"()": build_log_handler, "stream": "ext://sys.stdout"},
        },
        "formatters": {},
        "root": {"level": level, "handlers": [STDOUT_HANDLER_NAME]},
        "loggers": {
            # No handlers of its own: the records reach the root handler.
            "gunicorn.error": {"level": level, "handlers": [], "propagate": True},
            # Dropped: the app logs each request itself, with its id and duration.
            "gunicorn.access": {"handlers": [], "propagate": False},
        },
    }


def configure_logging(level: str) -> None:
    """Send every log record, ours and third-party, to stdout as JSON.

    Safe to call more than once (tests and CLI commands create several apps):
    the handler installed by a previous call is replaced, while handlers added
    by others, such as log capture in tests, are left alone.
    """
    root = logging.getLogger()
    for handler in [h for h in root.handlers if h.get_name() == STDOUT_HANDLER_NAME]:
        root.removeHandler(handler)
    handler = build_log_handler(sys.stdout)
    handler.set_name(STDOUT_HANDLER_NAME)
    root.addHandler(handler)
    root.setLevel(level)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_request_id() -> str:
    """Return the id of the current request, choosing it on first use.

    Resolved lazily so error handlers that run before any ``before_request``
    hook still get an id.
    """
    if "request_id" not in g:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        valid = _REQUEST_ID_PATTERN.fullmatch(incoming) is not None
        g.request_id = incoming if valid else str(uuid.uuid4())
    request_id: str = g.request_id
    return request_id


def init_request_logging(app: Flask) -> None:
    """Tag every request with an id and write one access log line per response."""
    app.before_request(_start_request)
    app.after_request(_finish_request)


def _start_request() -> None:
    g.request_started_at = time.perf_counter()
    get_request_id()


def _finish_request(response: Response) -> Response:
    response.headers[REQUEST_ID_HEADER] = get_request_id()
    duration_ms = (time.perf_counter() - g.request_started_at) * 1000
    access_logger.info(
        "request completed",
        extra={
            "method": request.method,
            # The path only: query strings can carry values that do not belong in logs.
            "path": request.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response
