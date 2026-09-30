"""Server-side state of refresh tokens: rotation, revocation and reuse detection.

Refresh tokens are JWTs, so their signature and expiry are checked without
any lookup. What a JWT cannot say by itself is whether it has already been
used or revoked. Redis records that, and every key expires when the token it
describes would have, so nothing needs cleaning up.

Each login starts a token *family*, and every rotation passes the family on
to the new token. A token that is presented again after it was rotated means
two parties hold it, one of them probably a thief. There is no telling which
one, so the whole family is revoked and both must log in again.

One legitimate case looks the same: several browser tabs (for example after
a session restore) refreshing with the same cookie at the same moment. Reuse
within a short grace window is therefore accepted.
"""

import logging
import math
import time
from collections.abc import Callable

from redis import Redis

from app.errors import Unauthorized

logger = logging.getLogger(__name__)

DEFAULT_REUSE_GRACE_SECONDS = 10.0

_PREFIX = "auth:refresh"


class RefreshTokenReused(Unauthorized):
    default_message = "The token has been revoked."


class RefreshTokenStore:
    def __init__(
        self,
        redis: Redis,
        *,
        family_ttl_seconds: int,
        reuse_grace_seconds: float = DEFAULT_REUSE_GRACE_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """``family_ttl_seconds`` is the refresh token lifetime: no token of a
        family can outlive it, counted from when the family is revoked."""
        self._redis = redis
        self._family_ttl_seconds = family_ttl_seconds
        self._reuse_grace_seconds = reuse_grace_seconds
        self._clock = clock

    def is_revoked(self, jti: str, family: str) -> bool:
        """Whether the token was logged out, or belongs to a revoked family."""
        return bool(self._redis.exists(_revoked_key(jti), _family_key(family)))

    def revoke(self, jti: str, expires_at: int) -> None:
        """Deny the token for the rest of its lifetime (logout)."""
        self._redis.set(_revoked_key(jti), "1", ex=self._remaining_seconds(expires_at))

    def rotate(self, jti: str, family: str, expires_at: int) -> None:
        """Spend the token on a refresh, or raise ``RefreshTokenReused``.

        The first use claims the token atomically (SET NX), so two racing
        refreshes can never both count as the first. A later use within the
        grace window is a concurrent tab and is allowed; after it, the whole
        family is revoked.
        """
        now = self._clock()
        first_used_at = self._redis.set(
            _used_key(jti), repr(now), nx=True, get=True, ex=self._remaining_seconds(expires_at)
        )
        if first_used_at is None:
            return
        if now - float(first_used_at) <= self._reuse_grace_seconds:
            return
        self._redis.set(_family_key(family), "1", ex=self._family_ttl_seconds)
        logger.warning(
            "refresh token reused after rotation; token family revoked",
            extra={"token_family": family, "jti": jti},
        )
        raise RefreshTokenReused

    def _remaining_seconds(self, expires_at: int) -> int:
        # At least 1: Redis rejects a zero or negative expiry, and a token
        # that expires this second still needs its record until it does.
        return max(1, math.ceil(expires_at - self._clock()))


def _used_key(jti: str) -> str:
    return f"{_PREFIX}:used:{jti}"


def _revoked_key(jti: str) -> str:
    return f"{_PREFIX}:revoked:{jti}"


def _family_key(family: str) -> str:
    return f"{_PREFIX}:revoked-family:{family}"
