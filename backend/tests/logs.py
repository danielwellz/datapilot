"""Capture what the application logs, as parsed JSON lines."""

import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.logging import build_log_handler


class LogCapture:
    def __init__(self) -> None:
        self.stream = io.StringIO()

    @property
    def text(self) -> str:
        return self.stream.getvalue()

    def records(self, logger: str | None = None) -> list[dict[str, Any]]:
        """Every JSON line logged so far, optionally only those from one logger."""
        records = [json.loads(line) for line in self.text.splitlines()]
        return [r for r in records if logger is None or r["logger"] == logger]


@contextmanager
def capture_logs() -> Iterator[LogCapture]:
    """Record every log line through the same JSON handler production uses."""
    capture = LogCapture()
    handler = build_log_handler(capture.stream)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield capture
    finally:
        root.removeHandler(handler)
