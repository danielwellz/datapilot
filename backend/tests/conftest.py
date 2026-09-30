from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.config import Settings
from tests.logs import LogCapture, capture_logs
from tests.settings import make_test_settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    return make_test_settings()


@pytest.fixture(scope="session")
def app(settings: Settings) -> Iterator[Flask]:
    app = create_app(settings)
    with app.app_context():
        yield app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def captured_logs() -> Iterator[LogCapture]:
    with capture_logs() as capture:
        yield capture
