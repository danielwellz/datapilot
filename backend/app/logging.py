"""JSON logging to stdout, request ids and the access log."""

import logging
import re
import sys
import time
import uuid
from typing import IO

from flask import Flask, Response, g, has_request_context, request
from pythonjsonlogger.json import JsonFormatter

REQUEST_ID_HEADER = "X-Request-ID"

# Client-supplied ids end up in every log line, so anything that could forge
# or break a line (newlines, quotes, very long values) is replaced.
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")

access_logger = logging.getLogger("app.access")


class RequestIdFilter(logging.Filter):
    """Attach the current request id (or ``None`` outside a request) to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() if has_request_context() else None
        return True


class _AppLogHandler(logging.StreamHandler[IO[str]]):
    """Marker type so ``configure_logging`` can replace its own handler on reconfiguration."""


def build_log_handler(stream: IO[str]) -> logging.Handler:
    """Create a handler that writes one JSON object per line to ``stream``."""
    handler = _AppLogHandler(stream)
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


def configure_logging(level: str) -> None:
    """Send every log record, ours and third-party, to stdout as JSON.

    Safe to call more than once (tests and CLI commands create several apps):
    the previous handler installed here is replaced, while handlers added by
    others, such as pytest's log capture, are left alone.
    """
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, _AppLogHandler)]:
        root.removeHandler(handler)
    root.addHandler(build_log_handler(sys.stdout))
    root.setLevel(level)


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
