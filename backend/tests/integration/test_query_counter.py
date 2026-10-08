from sqlalchemy import text
from sqlalchemy.orm import Session, scoped_session

from tests.factories import create_customer
from tests.integration.conftest import QueryCounter


def test_query_counter_records_each_statement_inside_the_block(
    db_session: scoped_session[Session], count_queries: QueryCounter
) -> None:
    db_session.execute(text("SELECT 1"))

    with count_queries() as statements:
        db_session.execute(text("SELECT 2"))
        db_session.execute(text("SELECT 3"))
    db_session.execute(text("SELECT 4"))

    assert statements == ["SELECT 2", "SELECT 3"]


def test_query_counter_ignores_the_savepoints_of_the_test_harness(
    count_queries: QueryCounter,
) -> None:
    with count_queries() as statements:
        create_customer()

    assert len(statements) == 1
    assert statements[0].startswith("INSERT INTO customers")
