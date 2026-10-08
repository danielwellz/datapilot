from datetime import UTC, datetime, timedelta, timezone

from flask.testing import FlaskClient

from tests.factories import create_customer, create_order, create_product

URL = "/api/meta"


def test_meta_lists_the_filter_options_present_in_the_data(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    ana = create_customer(country="DE")
    create_customer(country="US")
    create_customer(country="DE")
    bottle = create_product(category="Sports")
    create_product(category="Home")
    create_product(category="Sports")
    create_order(ana, [(bottle, 1)], created_at=datetime(2024, 2, 1, 9, 0, tzinfo=UTC))
    # 23:30 at UTC-5 is already the next day in UTC.
    late_evening = datetime(2026, 3, 9, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    create_order(ana, [(bottle, 2)], created_at=late_evening)

    response = client.get(URL, headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "countries": ["DE", "US"],
        "statuses": ["paid", "refunded", "cancelled"],
        "channels": ["web", "mobile", "marketplace"],
        "categories": ["Home", "Sports"],
        "first_order_date": "2024-02-01",
        "last_order_date": "2026-03-10",
    }


def test_meta_without_data_has_no_order_dates(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    body = client.get(URL, headers=auth_headers).get_json()

    assert body["countries"] == []
    assert body["categories"] == []
    assert body["first_order_date"] is None
    assert body["last_order_date"] is None


def test_meta_requires_an_access_token(client: FlaskClient) -> None:
    response = client.get(URL)

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"
