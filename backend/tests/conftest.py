"""Fixtures shared by every test.

The application is built once per session from explicit test settings. No
application context stays pushed between requests: each test client request
gets its own context and its own ``g``, exactly as in production. Tests that
use the app outside a request ask for ``app_context``.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.config import Settings
from app.extensions import db, get_readonly_engine, get_redis
from tests.logs import LogCapture, capture_logs
from tests.settings import make_test_settings

AppFactory = Callable[..., Flask]


def close_app_resources(app: Flask) -> None:
    """Close pooled database and Redis connections, which warn if left open."""
    with app.app_context():
        db.engine.dispose()
        get_readonly_engine().dispose()
        get_redis().close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return make_test_settings()


@pytest.fixture(scope="session")
def app(settings: Settings) -> Iterator[Flask]:
    app = create_app(settings)
    yield app
    close_app_resources(app)


@pytest.fixture
def make_app() -> Iterator[AppFactory]:
    """Build extra apps with overridden settings; their connections are closed afterwards."""
    apps: list[Flask] = []

    def factory(**overrides: Any) -> Flask:
        app = create_app(make_test_settings(**overrides))
        apps.append(app)
        return app

    yield factory
    for app in apps:
        close_app_resources(app)


@pytest.fixture
def app_context(app: Flask) -> Iterator[None]:
    with app.app_context():
        yield


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def captured_logs() -> Iterator[LogCapture]:
    with capture_logs() as capture:
        yield capture
