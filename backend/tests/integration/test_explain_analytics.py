from datetime import date

import pytest
from sqlalchemy.orm import Session, scoped_session

from scripts.explain_analytics import build_scenarios
from scripts.plans import measure, render
from tests.factories import create_customer, create_order, create_product
from tests.integration.analytics.conftest import at


@pytest.fixture
def session(db_session: scoped_session[Session]) -> Session:
    return db_session()


def test_every_analytics_scenario_is_explained_as_one_statement(session: Session) -> None:
    customer = create_customer(country="DE", signed_up_at=at("2026-01-05"))
    create_order(
        customer, [(create_product(category="Electronics"), 2)], created_at=at("2026-02-10")
    )

    measurements = [
        measure(session, scenario, runs=1)
        for scenario in build_scenarios(session, date(2026, 3, 15))
    ]

    assert [m.scenario.name for m in measurements] == [
        "summary-30",
        "summary-365",
        "revenue-monthly-24",
        "revenue-monthly-36",
        "top-customers",
        "top-customers-de",
        "products",
        "products-category",
        "cohorts-12",
        "cohorts-24",
    ]
    for measurement in measurements:
        assert measurement.statements == 1
        assert measurement.scenario.name in render(measurement)
