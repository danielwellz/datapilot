import pytest
from redis import Redis

from app.services.refresh_tokens import RefreshTokenReused, RefreshTokenStore
from tests.logs import LogCapture

NOW = 1_800_000_000.0
EXPIRES_AT = int(NOW) + 3600
FAMILY_TTL = 7 * 24 * 3600


class FakeClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(redis_client: Redis, clock: FakeClock) -> RefreshTokenStore:
    return RefreshTokenStore(
        redis_client, family_ttl_seconds=FAMILY_TTL, reuse_grace_seconds=10, clock=clock
    )


def test_a_fresh_token_is_not_revoked(store: RefreshTokenStore) -> None:
    assert store.is_revoked("jti-1", "family-1") is False


def test_revoke_denies_the_token_for_its_remaining_lifetime(
    store: RefreshTokenStore, redis_client: Redis
) -> None:
    store.revoke("jti-1", EXPIRES_AT)

    assert store.is_revoked("jti-1", "family-1") is True
    assert store.is_revoked("jti-2", "family-1") is False
    assert redis_client.ttl("auth:refresh:revoked:jti-1") == 3600


def test_revoking_a_token_that_expires_now_still_records_it(
    store: RefreshTokenStore, redis_client: Redis
) -> None:
    store.revoke("jti-1", int(NOW))

    assert redis_client.ttl("auth:refresh:revoked:jti-1") == 1


def test_first_rotation_spends_the_token_until_it_expires(
    store: RefreshTokenStore, redis_client: Redis
) -> None:
    store.rotate("jti-1", "family-1", EXPIRES_AT)

    assert redis_client.ttl("auth:refresh:used:jti-1") == 3600
    assert store.is_revoked("jti-1", "family-1") is False


def test_reuse_within_the_grace_window_is_allowed(
    store: RefreshTokenStore, clock: FakeClock
) -> None:
    store.rotate("jti-1", "family-1", EXPIRES_AT)
    clock.now = NOW + 10

    store.rotate("jti-1", "family-1", EXPIRES_AT)

    assert store.is_revoked("jti-2", "family-1") is False


def test_reuse_after_the_grace_window_revokes_the_whole_family(
    store: RefreshTokenStore, clock: FakeClock, redis_client: Redis
) -> None:
    store.rotate("jti-1", "family-1", EXPIRES_AT)
    clock.now = NOW + 10.5

    with pytest.raises(RefreshTokenReused):
        store.rotate("jti-1", "family-1", EXPIRES_AT)

    assert store.is_revoked("jti-2", "family-1") is True
    assert store.is_revoked("jti-3", "family-2") is False
    assert redis_client.ttl("auth:refresh:revoked-family:family-1") == FAMILY_TTL


def test_grace_window_counts_from_the_first_use_not_the_latest(
    store: RefreshTokenStore, clock: FakeClock
) -> None:
    store.rotate("jti-1", "family-1", EXPIRES_AT)
    clock.now = NOW + 8
    store.rotate("jti-1", "family-1", EXPIRES_AT)
    clock.now = NOW + 16

    with pytest.raises(RefreshTokenReused):
        store.rotate("jti-1", "family-1", EXPIRES_AT)


def test_detected_reuse_is_logged_as_a_warning(
    store: RefreshTokenStore, clock: FakeClock, captured_logs: LogCapture
) -> None:
    store.rotate("jti-1", "family-1", EXPIRES_AT)
    clock.now = NOW + 60

    with pytest.raises(RefreshTokenReused):
        store.rotate("jti-1", "family-1", EXPIRES_AT)

    (line,) = captured_logs.records("app.services.refresh_tokens")
    assert line["level"] == "WARNING"
    assert line["token_family"] == "family-1"
    assert line["jti"] == "jti-1"
