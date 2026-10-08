import psycopg
import pytest
from flask import Flask
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, scoped_session

from app.config import Settings
from tests.conftest import AppFactory

ROLE_PASSWORD_SQL = text("SELECT rolpassword FROM pg_authid WHERE rolname = 'datapilot_readonly'")


def test_db_roles_lets_the_readonly_role_log_in_with_the_configured_password(
    app: Flask, settings: Settings
) -> None:
    result = app.test_cli_runner().invoke(args=["db-roles"])

    assert result.exit_code == 0, result.output
    engine = create_engine(str(settings.readonly_database_url))
    try:
        with engine.connect() as connection:
            current_user: str = connection.execute(text("SELECT current_user")).scalar_one()
    finally:
        engine.dispose()
    assert current_user == "datapilot_readonly"


def test_db_roles_stores_a_scram_verifier_and_never_prints_the_password(
    app: Flask, settings: Settings, db_session: scoped_session[Session]
) -> None:
    result = app.test_cli_runner().invoke(args=["db-roles"])

    stored: str = db_session.execute(ROLE_PASSWORD_SQL).scalar_one()
    password = settings.readonly_database_url.hosts()[0]["password"]
    assert password
    assert stored.startswith("SCRAM-SHA-256$")
    assert password not in stored
    assert password not in result.output


@pytest.mark.parametrize(
    ("readonly_database_url", "message"),
    [
        (
            "postgresql+psycopg://datapilot:secret@localhost:5433/datapilot_test",
            "must connect as datapilot_readonly, not 'datapilot'",
        ),
        (
            "postgresql+psycopg://datapilot_readonly@localhost:5433/datapilot_test",
            "has no password",
        ),
    ],
)
def test_db_roles_refuses_a_url_it_cannot_use(
    make_app: AppFactory, readonly_database_url: str, message: str
) -> None:
    app = make_app(readonly_database_url=readonly_database_url)

    result = app.test_cli_runner().invoke(args=["db-roles"])

    assert result.exit_code == 1
    assert message in result.output


def test_db_roles_asks_for_the_migrations_when_the_role_does_not_exist(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_role(*_args: object) -> None:
        raise psycopg.errors.UndefinedObject('role "datapilot_readonly" does not exist')

    monkeypatch.setattr("app.cli.set_readonly_role_password", missing_role)

    result = app.test_cli_runner().invoke(args=["db-roles"])

    assert result.exit_code == 1
    assert "run the migrations first (make db-upgrade)" in result.output
