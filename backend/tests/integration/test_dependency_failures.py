"""Outages of PostgreSQL or Redis, and slow statements, answer 503 rather than 500."""

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from app.extensions import db
from tests.conftest import AppFactory
from tests.factories import DEFAULT_PASSWORD, create_user
from tests.logs import LogCapture
from tests.tokens import access_token_for, bearer

# Nothing listens on port 1, so connections are refused at once.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://datapilot:datapilot@localhost:1/datapilot_test"
UNREACHABLE_REDIS_URL = "redis://localhost:1/15"
LOGIN = {"email": "ana@datapilot.dev", "password": DEFAULT_PASSWORD}


def _outage(captured_logs: LogCapture) -> str:
    (record,) = [r for r in captured_logs.records("app.errors") if r["level"] == "ERROR"]
    assert record["message"] == "dependency unavailable"
    dependency: str = record["dependency"]
    return dependency


def test_login_answers_503_and_logs_redis_when_redis_is_down(
    make_app: AppFactory, captured_logs: LogCapture
) -> None:
    client = make_app(redis_url=UNREACHABLE_REDIS_URL).test_client()

    response = client.post("/api/auth/login", json=LOGIN)

    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "service_unavailable"
    assert _outage(captured_logs) == "redis"


def test_login_answers_503_and_logs_the_database_when_it_is_down(
    client: FlaskClient, captured_logs: LogCapture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The harness binds db.session to the test's connection whatever the
    # app's URL, so the outage is staged on the session itself.
    engine = create_engine(UNREACHABLE_DATABASE_URL)
    monkeypatch.setattr(db, "session", scoped_session(sessionmaker(bind=engine)))

    response = client.post("/api/auth/login", json=LOGIN)

    engine.dispose()
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "service_unavailable"
    assert _outage(captured_logs) == "database"


def test_asking_answers_503_when_redis_holds_the_rate_limit_and_is_down(
    make_app: AppFactory, captured_logs: LogCapture
) -> None:
    app = make_app(redis_url=UNREACHABLE_REDIS_URL)
    headers = bearer(access_token_for(app, create_user()))

    response = app.test_client().post(
        "/api/ai/ask", json={"question": "How many orders?"}, headers=headers
    )

    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "service_unavailable"
    assert _outage(captured_logs) == "redis"


def _show_statement_timeout() -> str:
    value: str = db.session.execute(text("SHOW statement_timeout")).scalar_one()
    return value


def test_statements_in_a_request_are_capped_and_commands_are_not(
    make_app: AppFactory, db_session: scoped_session[Session]
) -> None:
    app: Flask = make_app(api_statement_timeout_ms=1500)

    with app.app_context():
        assert _show_statement_timeout() == "0"
    db_session.rollback()
    with app.test_request_context():
        assert _show_statement_timeout() == "1500ms"


def test_a_statement_over_the_cap_is_stopped_with_503(
    make_app: AppFactory, captured_logs: LogCapture
) -> None:
    app = make_app(api_statement_timeout_ms=50)

    @app.get("/api/slow")
    def slow() -> str:
        db.session.execute(text("SELECT pg_sleep(1)"))
        return "done"

    response = app.test_client().get("/api/slow")

    assert response.status_code == 503
    error = response.get_json()["error"]
    assert error["code"] == "statement_timeout"
    assert "Narrow the filters" in error["message"]
    (record,) = captured_logs.records("app.errors")
    assert (record["level"], record["message"]) == ("WARNING", "statement timed out")
    assert "pg_sleep" not in str(record)
