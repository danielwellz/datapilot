from datetime import timedelta

import pytest
from flask import Flask
from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.config import Settings
from app.extensions import Base, db, get_redis
from tests.conftest import AppFactory


@pytest.mark.usefixtures("app_context")
def test_redis_client_uses_configured_database_and_timeouts(settings: Settings) -> None:
    kwargs = get_redis().connection_pool.connection_kwargs

    assert settings.redis_url.path is not None
    assert kwargs["db"] == int(settings.redis_url.path.removeprefix("/"))
    assert kwargs["socket_timeout"] == 2.0
    assert kwargs["socket_connect_timeout"] == 2.0
    assert kwargs["decode_responses"] is True


@pytest.mark.usefixtures("app_context")
def test_database_engine_uses_configured_url(app: Flask, settings: Settings) -> None:
    url = db.engine.url

    assert url.render_as_string(hide_password=False) == str(settings.database_url)
    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"]["pool_pre_ping"] is True


def test_jwt_secret_comes_from_settings(app: Flask, settings: Settings) -> None:
    assert app.config["JWT_SECRET_KEY"] == settings.jwt_secret_key.get_secret_value()


def test_naming_convention_gives_constraints_deterministic_names() -> None:
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    Table("customers", metadata, Column("id", Integer, primary_key=True))
    orders = Table(
        "orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, ForeignKey("customers.id"), index=True),
        Column("number", String, unique=True),
        Column("total", Integer),
        CheckConstraint("total >= 0", name="total_not_negative"),
    )
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]

    ddl = str(CreateTable(orders).compile(dialect=dialect))
    (index,) = orders.indexes

    assert "CONSTRAINT pk_orders PRIMARY KEY" in ddl
    assert "CONSTRAINT fk_orders_customer_id_customers FOREIGN KEY" in ddl
    assert "CONSTRAINT uq_orders_number UNIQUE" in ddl
    assert "CONSTRAINT ck_orders_total_not_negative CHECK" in ddl
    assert "ix_orders_customer_id" in str(CreateIndex(index).compile(dialect=dialect))


def test_token_lifetimes_come_from_settings(make_app: AppFactory) -> None:
    app = make_app(jwt_access_ttl_minutes=5, jwt_refresh_ttl_days=2)

    assert app.config["JWT_ACCESS_TOKEN_EXPIRES"] == timedelta(minutes=5)
    assert app.config["JWT_REFRESH_TOKEN_EXPIRES"] == timedelta(days=2)


def test_refresh_cookie_is_strict_persistent_and_scoped_to_auth_endpoints(app: Flask) -> None:
    assert app.config["JWT_REFRESH_COOKIE_PATH"] == "/api/auth"
    assert app.config["JWT_COOKIE_SAMESITE"] == "Strict"
    assert app.config["JWT_COOKIE_CSRF_PROTECT"] is True
    assert app.config["JWT_SESSION_COOKIE"] is False


@pytest.mark.parametrize(("app_env", "secure"), [("test", False), ("production", True)])
def test_cookies_are_secure_only_in_production(
    make_app: AppFactory, app_env: str, secure: bool
) -> None:
    strong = "s" * 40
    app = make_app(app_env=app_env, secret_key=strong, jwt_secret_key=strong)

    assert app.config["JWT_COOKIE_SECURE"] is secure
