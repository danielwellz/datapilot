from datetime import datetime, timedelta, timezone

import pytest
from flask.testing import FlaskClient

from app.models import OrderStatus
from tests.factories import create_customer
from tests.integration.analytics.conftest import at, sale
from tests.integration.conftest import QueryCounter

URL = "/api/analytics/cohorts"


@pytest.fixture
def signups() -> None:
    """Today is 2026-03-15; months=3 gives the December, January and February cohorts.

    December (Ana, Ben, Cleo): paid in December: Ana; January: Ben;
    February: Ana and Cleo. January (Dev, Eva): January: Dev; February:
    Dev and Eva. February (Finn): nobody.
    """
    ana = create_customer(signed_up_at=at("2025-12-01", "00:00:00"))
    ben = create_customer(signed_up_at=at("2025-12-31", "23:59:59"))
    # 00:30 on January 1st at UTC+2 is still December 31st in UTC.
    cleo = create_customer(
        signed_up_at=datetime(2026, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    )
    dev = create_customer(signed_up_at=at("2026-01-08"))
    eva = create_customer(signed_up_at=at("2026-01-25"))
    create_customer(signed_up_at=at("2026-02-03"))
    # Outside the cohorts: November, and the current month.
    zed = create_customer(signed_up_at=at("2025-11-30", "23:59:59"))
    create_customer(signed_up_at=at("2026-03-01", "00:00:00"))

    # Two orders in one month count the customer once.
    sale(ana, "10.00", at("2025-12-05"))
    sale(ana, "10.00", at("2025-12-20"))
    sale(ana, "10.00", at("2026-02-10"))
    sale(ben, "10.00", at("2025-12-31", "23:59:59"), status=OrderStatus.REFUNDED)
    sale(ben, "10.00", at("2026-01-15"))
    sale(cleo, "10.00", at("2026-01-05"), status=OrderStatus.CANCELLED)
    sale(cleo, "10.00", at("2026-02-20"))
    sale(dev, "10.00", at("2026-01-10"))
    sale(dev, "10.00", at("2026-01-20"))
    sale(dev, "10.00", at("2026-02-01", "00:00:00"))
    # The current month is incomplete and not counted.
    sale(dev, "10.00", at("2026-03-03"))
    sale(eva, "10.00", at("2026-02-14"))
    sale(zed, "10.00", at("2025-12-10"))


def month(offset: int, active: int, rate: float) -> dict[str, object]:
    return {"months_since_signup": offset, "active_customers": active, "retention_rate": rate}


@pytest.mark.usefixtures("signups")
def test_cohorts_report_the_share_of_each_signup_month_ordering_in_later_months(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(URL, query_string={"months": 3}, headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "items": [
            {
                "cohort_month": "2025-12-01",
                "customers": 3,
                # One, one, then two of three customers.
                "retention": [month(0, 1, 0.3333), month(1, 1, 0.3333), month(2, 2, 0.6667)],
            },
            {
                "cohort_month": "2026-01-01",
                "customers": 2,
                "retention": [month(0, 1, 0.5), month(1, 2, 1.0)],
            },
            {
                # A month in which nobody ordered is still reported.
                "cohort_month": "2026-02-01",
                "customers": 1,
                "retention": [month(0, 0, 0.0)],
            },
        ]
    }


@pytest.mark.usefixtures("signups")
def test_fewer_months_return_only_the_newest_cohorts(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    body = client.get(URL, query_string={"months": 2}, headers=auth_headers).get_json()

    assert [cohort["cohort_month"] for cohort in body["items"]] == ["2026-01-01", "2026-02-01"]


def test_months_without_signups_have_no_cohort(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    create_customer(signed_up_at=at("2025-12-10"))

    body = client.get(URL, query_string={"months": 3}, headers=auth_headers).get_json()

    assert body == {
        "items": [
            {
                "cohort_month": "2025-12-01",
                "customers": 1,
                "retention": [month(0, 0, 0.0), month(1, 0, 0.0), month(2, 0, 0.0)],
            }
        ]
    }


def test_cohorts_cover_twelve_months_by_default(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    create_customer(signed_up_at=at("2025-03-01", "00:00:00"))
    create_customer(signed_up_at=at("2025-02-28", "23:59:59"))

    body = client.get(URL, headers=auth_headers).get_json()

    [cohort] = body["items"]
    assert cohort["cohort_month"] == "2025-03-01"
    # March 2025 to February 2026.
    assert len(cohort["retention"]) == 12


@pytest.mark.parametrize("query", [{"months": 0}, {"months": 25}, {"days": 30}])
def test_cohorts_reject_invalid_query_parameters(
    client: FlaskClient, auth_headers: dict[str, str], query: dict[str, object]
) -> None:
    assert client.get(URL, query_string=query, headers=auth_headers).status_code == 422


def test_cohorts_require_an_access_token(client: FlaskClient) -> None:
    assert client.get(URL).status_code == 401


@pytest.mark.usefixtures("signups")
def test_cohorts_run_one_query(
    client: FlaskClient, auth_headers: dict[str, str], count_queries: QueryCounter
) -> None:
    with count_queries() as statements:
        client.get(URL, headers=auth_headers)

    assert len([s for s in statements if "FROM customers" in s]) == 1


def test_cohorts_are_documented(client: FlaskClient) -> None:
    operation = client.get("/api/openapi.json").get_json()["paths"][URL]["get"]

    assert operation["tags"] == ["analytics"]
    assert [parameter["name"] for parameter in operation["parameters"]] == ["months"]
    assert set(operation["responses"]) == {"200", "401", "422"}
