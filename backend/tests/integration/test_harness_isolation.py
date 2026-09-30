"""Prove that nothing a test writes survives into the next test.

The tests in this module run in file order: the first writes, the second
checks that the write is gone.
"""

from collections.abc import Iterator

import pytest
from flask import Flask
from redis import Redis
from sqlalchemy import Column, Integer, MetaData, String, Table, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, scoped_session

from app.extensions import db

# Not part of the application schema: created for this module only.
probe_metadata = MetaData()
probes = Table(
    "harness_probes",
    probe_metadata,
    Column("id", Integer, primary_key=True),
    Column("label", String(50), nullable=False),
)
REDIS_KEY = "harness:probe"


@pytest.fixture(scope="module", autouse=True)
def probe_table(app: Flask) -> Iterator[None]:
    with app.app_context():
        probe_metadata.create_all(db.engine)
    yield
    with app.app_context():
        probe_metadata.drop_all(db.engine)


def count_probes() -> int:
    return db.session.execute(select(func.count()).select_from(probes)).scalar_one()


def test_committed_row_is_visible_inside_the_test_that_wrote_it(redis_client: Redis) -> None:
    db.session.execute(insert(probes).values(id=1, label="written by the first test"))
    db.session.commit()
    redis_client.set(REDIS_KEY, "written by the first test")

    assert count_probes() == 1
    assert redis_client.get(REDIS_KEY) == "written by the first test"


def test_row_and_key_from_the_previous_test_are_gone(redis_client: Redis) -> None:
    assert count_probes() == 0
    assert redis_client.get(REDIS_KEY) is None


def test_session_stays_usable_after_rolling_back_a_failed_statement(
    db_session: scoped_session[Session],
) -> None:
    db.session.execute(insert(probes).values(id=1, label="kept"))
    db.session.commit()

    with pytest.raises(IntegrityError):
        db.session.execute(insert(probes).values(id=1, label="duplicate key"))
    db.session.rollback()

    assert db.session is db_session
    assert db.session.execute(select(probes.c.label)).scalars().all() == ["kept"]
