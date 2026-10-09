import json
import logging
import logging.config
import uuid
from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.config import Settings
from app.logging import (
    REQUEST_ID_HEADER,
    STDOUT_HANDLER_NAME,
    configure_logging,
    gunicorn_log_config,
)
from tests.logs import LogCapture

app_logger = logging.getLogger("app.tests")


@pytest.fixture
def logging_app(settings: Settings) -> Flask:
    app = create_app(settings)

    @app.get("/ping")
    def ping() -> str:
        app_logger.info("handling ping")
        return "pong"

    return app


@pytest.fixture
def logging_client(logging_app: Flask) -> FlaskClient:
    return logging_app.test_client()


def test_response_carries_generated_request_id_when_none_is_sent(
    logging_client: FlaskClient,
) -> None:
    response = logging_client.get("/ping")

    assert uuid.UUID(response.headers[REQUEST_ID_HEADER]).version == 4


def test_response_echoes_a_valid_incoming_request_id(logging_client: FlaskClient) -> None:
    response = logging_client.get("/ping", headers={REQUEST_ID_HEADER: "edge-7f3a.42_x"})

    assert response.headers[REQUEST_ID_HEADER] == "edge-7f3a.42_x"


@pytest.mark.parametrize(
    "incoming",
    ["", "has space", 'quote"injection', "a" * 129, "line\\nbreak"],
)
def test_response_replaces_an_unsafe_incoming_request_id(
    logging_client: FlaskClient, incoming: str
) -> None:
    response = logging_client.get("/ping", headers={REQUEST_ID_HEADER: incoming})

    assert uuid.UUID(response.headers[REQUEST_ID_HEADER]).version == 4


def test_each_request_gets_its_own_request_id(logging_client: FlaskClient) -> None:
    first = logging_client.get("/ping").headers[REQUEST_ID_HEADER]
    second = logging_client.get("/ping").headers[REQUEST_ID_HEADER]

    assert first != second


def test_access_log_has_one_json_line_per_request_with_timing(
    logging_client: FlaskClient, captured_logs: LogCapture
) -> None:
    response = logging_client.get("/ping?token=secret", headers={REQUEST_ID_HEADER: "req-1"})

    access = captured_logs.records("app.access")
    assert len(access) == 1
    line = access[0]
    assert line["message"] == "request completed"
    assert line["level"] == "INFO"
    assert line["method"] == "GET"
    assert line["path"] == "/ping"
    assert line["status"] == response.status_code == 200
    assert isinstance(line["duration_ms"], float)
    assert line["duration_ms"] >= 0
    assert line["request_id"] == "req-1"
    assert "timestamp" in line
    assert "secret" not in captured_logs.text


def test_log_lines_written_while_handling_a_request_carry_its_id(
    logging_client: FlaskClient, captured_logs: LogCapture
) -> None:
    logging_client.get("/ping", headers={REQUEST_ID_HEADER: "req-2"})

    (handler_line,) = captured_logs.records("app.tests")
    assert handler_line["message"] == "handling ping"
    assert handler_line["request_id"] == "req-2"


def test_log_lines_outside_a_request_have_no_request_id(captured_logs: LogCapture) -> None:
    app_logger.warning("background work")

    (line,) = captured_logs.records("app.tests")
    assert line["request_id"] is None


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers = handlers
    root.setLevel(level)


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_replaces_its_own_handler_and_keeps_others(
    captured_logs: LogCapture,
) -> None:
    root = logging.getLogger()

    configure_logging("DEBUG")
    configure_logging("WARNING")
    app_logger.warning("still captured")

    ours = [h for h in root.handlers if h.get_name() == STDOUT_HANDLER_NAME]
    assert len(ours) == 1
    assert root.level == logging.WARNING
    assert [line["message"] for line in captured_logs.records("app.tests")] == ["still captured"]


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_keeps_http_client_request_lines_out_of_debug_logs() -> None:
    configure_logging("DEBUG")

    assert logging.getLogger("httpx2").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("httpcore2.connection").getEffectiveLevel() == logging.WARNING


@pytest.fixture
def restore_gunicorn_loggers() -> Iterator[None]:
    loggers = [logging.getLogger(name) for name in ("gunicorn.error", "gunicorn.access")]
    saved = [(log, list(log.handlers), log.level, log.propagate) for log in loggers]
    yield
    for log, handlers, level, propagate in saved:
        log.handlers, log.propagate = handlers, propagate
        log.setLevel(level)


@pytest.mark.usefixtures("restore_root_logger", "restore_gunicorn_loggers")
def test_gunicorn_records_become_json_lines_and_its_access_lines_are_dropped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # What Gunicorn applies in the master, then what each worker's create_app does.
    logging.config.dictConfig(gunicorn_log_config("INFO"))
    configure_logging("INFO")

    logging.getLogger("gunicorn.error").info("Booting worker with pid: 7")
    logging.getLogger("gunicorn.access").info('"GET /api/health HTTP/1.1" 200')

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    (line,) = lines
    assert (line["level"], line["logger"], line["message"]) == (
        "INFO",
        "gunicorn.error",
        "Booting worker with pid: 7",
    )
    root = logging.getLogger()
    assert [h.get_name() for h in root.handlers].count(STDOUT_HANDLER_NAME) == 1
