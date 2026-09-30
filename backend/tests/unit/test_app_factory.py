import pytest
from flask import Flask

from app import create_app
from app.config import Settings, current_settings, get_settings
from tests.settings import make_test_settings


def test_create_app_returns_flask_application_named_after_package(settings: Settings) -> None:
    app = create_app(settings)

    assert isinstance(app, Flask)
    assert app.name == "app"


def test_create_app_returns_a_new_instance_on_every_call(settings: Settings) -> None:
    first = create_app(settings)
    second = create_app(settings)

    first.config["MARKER"] = "first"

    assert first is not second
    assert "MARKER" not in second.config


def test_create_app_uses_injected_settings() -> None:
    settings = make_test_settings(secret_key="injected-secret")

    app = create_app(settings)

    assert app.config["SECRET_KEY"] == "injected-secret"
    assert app.testing is True
    with app.app_context():
        assert current_settings() is settings


def test_create_app_reads_environment_when_no_settings_are_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name, value in {
        "APP_ENV": "development",
        "SECRET_KEY": "secret-from-environment",
        "JWT_SECRET_KEY": "jwt-secret-from-environment",
        "DATABASE_URL": "postgresql+psycopg://u:p@db.internal:5432/app",
        "REDIS_URL": "redis://cache.internal:6379/0",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        app = create_app()
    finally:
        get_settings.cache_clear()

    assert app.config["SECRET_KEY"] == "secret-from-environment"
    assert app.testing is False


def test_create_app_does_not_serve_static_files(settings: Settings) -> None:
    app = create_app(settings)

    assert [rule.rule for rule in app.url_map.iter_rules()] == []
