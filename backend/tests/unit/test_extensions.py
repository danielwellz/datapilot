from flask import Flask
from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.config import Settings
from app.extensions import Base, db, get_redis


def test_redis_client_uses_configured_database_and_timeouts(app: Flask, settings: Settings) -> None:
    kwargs = get_redis().connection_pool.connection_kwargs

    assert settings.redis_url.path is not None
    assert kwargs["db"] == int(settings.redis_url.path.removeprefix("/"))
    assert kwargs["socket_timeout"] == 2.0
    assert kwargs["socket_connect_timeout"] == 2.0
    assert kwargs["decode_responses"] is True


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
