"""The analytics and meta endpoints are answered from Redis through cache-aside."""

from datetime import date

import pytest
from flask import Flask
from flask.testing import FlaskClient
from redis import Redis

from app import clock
from app.services.cache import DATA_VERSION_KEY
from tests.conftest import AppFactory
from tests.factories import create_customer, create_user
from tests.integration.analytics.conftest import at, sale
from tests.integration.conftest import QueryCounter
from tests.logs import LogCapture
from tests.tokens import access_token_for, bearer

ANALYTICS_URLS = [
    "/api/analytics/summary",
    "/api/analytics/revenue-monthly",
    "/api/analytics/top-customers",
    "/api/analytics/products",
    "/api/analytics/cohorts",
]
SUMMARY = "/api/analytics/summary"


def revenue(client: FlaskClient, headers: dict[str, str]) -> tuple[str, str]:
    response = client.get(SUMMARY, query_string={"days": 7}, headers=headers)
    return response.headers["X-Cache"], response.get_json()["revenue"]["current"]


@pytest.mark.parametrize("url", [*ANALYTICS_URLS, "/api/meta"])
def test_first_request_misses_and_the_same_request_then_hits(
    client: FlaskClient, auth_headers: dict[str, str], url: str
) -> None:
    sale(create_customer(signed_up_at=at("2025-12-01")), "10.00", at("2026-02-10"))

    first = client.get(url, headers=auth_headers)
    second = client.get(url, headers=auth_headers)

    assert (first.status_code, first.headers["X-Cache"]) == (200, "MISS")
    assert (second.status_code, second.headers["X-Cache"]) == (200, "HIT")
    assert second.content_type == "application/json"
    assert second.get_json() == first.get_json()


def test_a_hit_runs_no_analytics_query(
    client: FlaskClient, auth_headers: dict[str, str], count_queries: QueryCounter
) -> None:
    client.get(SUMMARY, headers=auth_headers)

    with count_queries() as statements:
        response = client.get(SUMMARY, headers=auth_headers)

    assert response.headers["X-Cache"] == "HIT"
    assert not [s for s in statements if "FROM orders" in s]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # Defaults are filled in before the key is built.
        ({}, {"days": 30}),
        ({"days": "7"}, {"days": 7}),
    ],
)
def test_equal_requests_share_an_entry_however_they_are_spelled(
    client: FlaskClient,
    auth_headers: dict[str, str],
    first: dict[str, object],
    second: dict[str, object],
) -> None:
    client.get(SUMMARY, query_string=first, headers=auth_headers)

    response = client.get(SUMMARY, query_string=second, headers=auth_headers)

    assert response.headers["X-Cache"] == "HIT"


def test_country_codes_share_an_entry_in_either_case(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    url = "/api/analytics/top-customers"
    client.get(url, query_string={"country": "us", "limit": 5}, headers=auth_headers)

    response = client.get(url, query_string={"limit": 5, "country": "US"}, headers=auth_headers)

    assert response.headers["X-Cache"] == "HIT"


def test_different_parameters_get_their_own_entries(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    client.get(SUMMARY, query_string={"days": 7}, headers=auth_headers)

    response = client.get(SUMMARY, query_string={"days": 8}, headers=auth_headers)

    assert response.headers["X-Cache"] == "MISS"


def test_the_cache_is_shared_by_every_user(client: FlaskClient, app: Flask) -> None:
    first = bearer(access_token_for(app, create_user()))
    second = bearer(access_token_for(app, create_user()))
    client.get(SUMMARY, headers=first)

    assert client.get(SUMMARY, headers=second).headers["X-Cache"] == "HIT"


def test_a_new_data_version_replaces_cached_numbers_at_once(
    client: FlaskClient, auth_headers: dict[str, str], redis_client: Redis
) -> None:
    sale(create_customer(), "10.00", at("2026-03-10"))
    assert revenue(client, auth_headers) == ("MISS", "10.00")

    # New data alone is not visible until the version changes, which is
    # what every seed does after it commits.
    sale(create_customer(), "5.00", at("2026-03-11"))
    assert revenue(client, auth_headers) == ("HIT", "10.00")

    redis_client.incr(DATA_VERSION_KEY)

    assert revenue(client, auth_headers) == ("MISS", "15.00")
    assert revenue(client, auth_headers) == ("HIT", "15.00")


def test_a_new_day_is_computed_afresh(
    client: FlaskClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sale(create_customer(), "10.00", at("2026-03-15"))
    assert revenue(client, auth_headers) == ("MISS", "0.00")

    # The next day, yesterday's period ends with the 15th.
    monkeypatch.setattr(clock, "utc_today", lambda: date(2026, 3, 16))

    assert revenue(client, auth_headers) == ("MISS", "10.00")


def test_cached_entries_expire_after_ten_minutes(
    client: FlaskClient, auth_headers: dict[str, str], redis_client: Redis
) -> None:
    client.get(SUMMARY, headers=auth_headers)

    [key] = redis_client.keys("cache:analytics:summary:*")

    assert key == "cache:analytics:summary:v0:as_of=2026-03-15&days=30"
    assert 590 < redis_client.ttl(key) <= 600


@pytest.mark.parametrize(("query", "status"), [({"days": 0}, 422), ({"days": 7, "extra": 1}, 422)])
def test_rejected_requests_are_neither_cached_nor_marked(
    client: FlaskClient,
    auth_headers: dict[str, str],
    redis_client: Redis,
    query: dict[str, object],
    status: int,
) -> None:
    response = client.get(SUMMARY, query_string=query, headers=auth_headers)

    assert response.status_code == status
    assert "X-Cache" not in response.headers
    assert redis_client.keys("cache:*") == []


def test_unauthenticated_requests_never_reach_the_cache(
    client: FlaskClient, redis_client: Redis
) -> None:
    client.get(SUMMARY, headers=bearer("not-a-token"))
    response = client.get(SUMMARY)

    assert response.status_code == 401
    assert "X-Cache" not in response.headers
    assert redis_client.keys("cache:*") == []


@pytest.mark.parametrize("url", [*ANALYTICS_URLS, "/api/meta"])
def test_endpoints_still_answer_when_redis_is_down(
    make_app: AppFactory, url: str, captured_logs: LogCapture
) -> None:
    # Port 1 refuses connections at once, like a stopped Redis.
    app = make_app(redis_url="redis://localhost:1/15")
    headers = bearer(access_token_for(app, create_user()))

    response = app.test_client().get(url, headers=headers)

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "BYPASS"
    [warning] = captured_logs.records("app.services.cache")
    assert warning["level"] == "WARNING"
