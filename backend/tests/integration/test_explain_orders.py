from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, scoped_session

from app.models import OrderStatus
from scripts.explain_orders import build_scenarios
from scripts.plans import measure, outline, render, summary_table
from tests.factories import create_customer, create_order, create_product


@pytest.fixture
def session(db_session: scoped_session[Session]) -> Session:
    return db_session()


def test_every_scenario_is_explained_with_its_real_statements(session: Session) -> None:
    product = create_product()
    customers = [create_customer(country="DE"), create_customer(country="DK")]
    start = datetime(2025, 1, 1, tzinfo=UTC)
    for day in range(6):
        create_order(
            customers[day % 2],
            [(product, 1)],
            status=OrderStatus.CANCELLED if day % 3 == 0 else OrderStatus.PAID,
            created_at=start + timedelta(days=day),
        )

    measurements = [measure(session, scenario, runs=2) for scenario in build_scenarios(session, 3)]

    statements = {m.scenario.name: m.statements for m in measurements}
    assert statements == {
        "list-default": 1,
        "list-country-90-days": 1,
        "list-customer-history": 1,
        "list-by-total": 1,
        "list-deep-keyset": 1,
        "list-deep-offset": 1,
        "list-rare-filters": 1,
        "order-detail": 2,
        "meta": 3,
    }
    for measurement in measurements:
        assert len(measurement.execution_ms) == 2
        assert len(measurement.outlines) == measurement.statements
        assert measurement.scenario.name in render(measurement)
    assert summary_table(measurements).count("\n") == len(measurements) + 1


def test_scenarios_need_orders_to_measure(session: Session) -> None:
    with pytest.raises(SystemExit, match="no orders"):
        build_scenarios(session, 1)


def test_scenarios_need_as_many_orders_as_the_depth(session: Session) -> None:
    create_order(create_customer(), [(create_product(), 1)])

    with pytest.raises(SystemExit, match="fewer than 2 orders"):
        build_scenarios(session, 2)


def test_outline_shows_scan_direction_index_rows_and_filtering() -> None:
    plan = {
        "Node Type": "Limit",
        "Actual Rows": 26,
        "Actual Loops": 1,
        "Plans": [
            {
                "Node Type": "Index Scan",
                "Scan Direction": "Backward",
                "Index Name": "ix_orders_created_at_id",
                "Relation Name": "orders",
                "Actual Rows": 26,
                "Actual Loops": 1,
                "Rows Removed by Filter": 1300,
            },
            {
                "Node Type": "Gather Merge",
                "Actual Rows": 3,
                "Actual Loops": 2,
                "Workers Launched": 2,
                "Sort Method": "top-N heapsort",
            },
        ],
    }

    assert outline(plan) == [
        "Limit (rows=26)",
        "  Index Scan Backward using ix_orders_created_at_id on orders "
        "(rows=26, removed by filter=1300)",
        "  Gather Merge (rows=3, loops=2, workers=2, sort=top-N heapsort)",
    ]
