from decimal import Decimal

import pytest
from flask.testing import FlaskClient

from app.extensions import db
from app.models import OrderStatus
from tests.factories import create_customer, create_order, create_product
from tests.integration.analytics.conftest import at
from tests.integration.conftest import QueryCounter

URL = "/api/analytics/products"


@pytest.fixture
def product_ids() -> dict[str, int]:
    """Today is 2026-03-15; the default 365 days are 2025-03-15 to 2026-03-14.

    Paid revenue in the period: Home: Lamp 3 x 100 = 300, Mug 4 x 25 = 100
    (category 400); Books: Novel 5 x 20 = 100, Atlas 1 x 50 = 50 (category
    150). Office: Pen never sold.
    """
    ana = create_customer()
    lamp = create_product(name="Lamp", category="Home", price="100.00")
    mug = create_product(name="Mug", category="Home", price="25.00")
    novel = create_product(name="Novel", category="Books", price="20.00")
    atlas = create_product(name="Atlas", category="Books", price="50.00")
    pen = create_product(name="Pen", category="Office", price="5.00")

    create_order(ana, [(lamp, 2), (mug, 4)], created_at=at("2025-06-01"))
    create_order(ana, [(lamp, 1), (novel, 5)], created_at=at("2026-03-14", "23:59:59"))
    create_order(ana, [(atlas, 1)], created_at=at("2025-12-01"))
    create_order(ana, [(atlas, 10)], status=OrderStatus.REFUNDED, created_at=at("2026-01-01"))
    # The instant before the period starts.
    create_order(ana, [(novel, 100)], created_at=at("2025-03-14", "23:59:59"))

    # Revenue is what was paid, not what the catalog says today.
    atlas.price = Decimal("999.00")
    db.session.commit()
    return {p.name: p.id for p in (lamp, mug, novel, atlas, pen)}


def item(
    product_ids: dict[str, int],
    rank: int,
    name: str,
    category: str,
    revenue: str,
    units: int,
    share: float,
) -> dict[str, object]:
    return {
        "rank": rank,
        "product_id": product_ids[name],
        "name": name,
        "category": category,
        "revenue": revenue,
        "units": units,
        "category_share": share,
    }


def test_products_are_ranked_by_revenue_with_their_share_of_the_category(
    client: FlaskClient, auth_headers: dict[str, str], product_ids: dict[str, int]
) -> None:
    response = client.get(URL, headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json()["items"] == [
        # 300 of Home's 400.
        item(product_ids, 1, "Lamp", "Home", "300.00", 3, 0.75),
        # Mug and Novel tie on 100.00 and share rank 2; Atlas is next, rank 3.
        item(product_ids, 2, "Mug", "Home", "100.00", 4, 0.25),
        # 100 of Books' 150.
        item(product_ids, 2, "Novel", "Books", "100.00", 5, 0.6667),
        item(product_ids, 3, "Atlas", "Books", "50.00", 1, 0.3333),
    ]


def test_shares_cover_the_whole_category_even_when_the_limit_cuts_it(
    client: FlaskClient, auth_headers: dict[str, str], product_ids: dict[str, int]
) -> None:
    body = client.get(URL, query_string={"limit": 2}, headers=auth_headers).get_json()

    # Atlas is not returned, but Novel's share still counts Atlas's revenue.
    assert body["items"] == [
        item(product_ids, 1, "Lamp", "Home", "300.00", 3, 0.75),
        item(product_ids, 2, "Mug", "Home", "100.00", 4, 0.25),
        item(product_ids, 2, "Novel", "Books", "100.00", 5, 0.6667),
    ]


def test_a_category_filter_ranks_within_that_category(
    client: FlaskClient, auth_headers: dict[str, str], product_ids: dict[str, int]
) -> None:
    body = client.get(URL, query_string={"category": "Books"}, headers=auth_headers).get_json()

    assert body["items"] == [
        item(product_ids, 1, "Novel", "Books", "100.00", 5, 0.6667),
        item(product_ids, 2, "Atlas", "Books", "50.00", 1, 0.3333),
    ]


@pytest.mark.usefixtures("product_ids")
@pytest.mark.parametrize("category", ["Office", "Garden"])
def test_a_category_without_paid_sales_returns_no_products(
    client: FlaskClient, auth_headers: dict[str, str], category: str
) -> None:
    body = client.get(URL, query_string={"category": category}, headers=auth_headers).get_json()

    assert body == {"items": []}


def test_a_category_that_earned_nothing_has_no_share(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    freebie = create_product(name="Sticker", category="Gifts", price="0.00")
    create_order(create_customer(), [(freebie, 3)], created_at=at("2026-03-01"))

    body = client.get(URL, headers=auth_headers).get_json()

    assert body["items"] == [
        {
            "rank": 1,
            "product_id": body["items"][0]["product_id"],
            "name": "Sticker",
            "category": "Gifts",
            "revenue": "0.00",
            "units": 3,
            "category_share": None,
        }
    ]


@pytest.mark.parametrize(
    "query",
    [{"limit": 0}, {"limit": 101}, {"days": 366}, {"category": ""}, {"category": "x" * 51}],
)
def test_product_ranking_rejects_invalid_query_parameters(
    client: FlaskClient, auth_headers: dict[str, str], query: dict[str, object]
) -> None:
    assert client.get(URL, query_string=query, headers=auth_headers).status_code == 422


def test_product_ranking_requires_an_access_token(client: FlaskClient) -> None:
    assert client.get(URL).status_code == 401


@pytest.mark.usefixtures("product_ids")
def test_product_ranking_runs_one_query(
    client: FlaskClient, auth_headers: dict[str, str], count_queries: QueryCounter
) -> None:
    with count_queries() as statements:
        client.get(URL, headers=auth_headers)

    assert len([s for s in statements if "FROM order_items" in s]) == 1


def test_product_ranking_is_documented(client: FlaskClient) -> None:
    operation = client.get("/api/openapi.json").get_json()["paths"][URL]["get"]

    assert operation["tags"] == ["analytics"]
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "category",
        "limit",
        "days",
    }
    assert set(operation["responses"]) == {"200", "401", "422"}
