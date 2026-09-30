from flask import Flask

from app import create_app


def test_create_app_returns_flask_application_named_after_package() -> None:
    app = create_app()

    assert isinstance(app, Flask)
    assert app.name == "app"


def test_create_app_returns_a_new_instance_on_every_call() -> None:
    first = create_app()
    second = create_app()

    first.config["MARKER"] = "first"

    assert first is not second
    assert "MARKER" not in second.config


def test_unknown_route_returns_not_found() -> None:
    client = create_app().test_client()

    response = client.get("/does-not-exist")

    assert response.status_code == 404
