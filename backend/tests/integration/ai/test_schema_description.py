import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, scoped_session

from app.ai.prompt import FEW_SHOT_EXAMPLES
from app.ai.schema_description import SchemaDescriptionError, describe_analytics_views
from app.ai.sql_guard import guard_sql
from tests.integration.ai.conftest import RunAsReadonly


def test_description_lists_every_view_with_typed_commented_columns(
    db_session: scoped_session[Session],
) -> None:
    description = describe_analytics_views(db_session())

    assert description.startswith("v_customers: Customers of the store.")
    assert "v_order_items: The products in each order" in description
    assert "  - total (numeric(12,2)): Order value in the store currency" in description
    assert "  - status (text): 'paid', 'refunded' or 'cancelled'." in description
    assert "  - country (character(2)): ISO 3166-1 alpha-2 country code" in description
    assert "email" not in description
    assert "password" not in description


def test_description_fails_clearly_when_the_views_are_missing(
    db_session: scoped_session[Session],
) -> None:
    with db_session.begin_nested():
        db_session.execute(text("DROP VIEW analytics.v_products"))

        with pytest.raises(SchemaDescriptionError, match="missing: v_products"):
            describe_analytics_views(db_session())


@pytest.mark.parametrize(
    "sql",
    [example.answer.sql for example in FEW_SHOT_EXAMPLES if example.answer.sql],
)
def test_few_shot_queries_run_on_postgresql_as_the_readonly_role(
    run_as_readonly: RunAsReadonly, sql: str
) -> None:
    guarded = guard_sql(sql, max_rows=1000)

    run_as_readonly(guarded.sql)
