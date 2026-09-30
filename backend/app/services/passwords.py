"""Password hashing with argon2id."""

import secrets
from functools import cached_property

from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import VerifyMismatchError


class PasswordHasher:
    """Hashes and verifies passwords, and spots hashes made with outdated parameters.

    The argon2 parameters default to argon2-cffi's recommended profile
    (RFC 9106, low memory). Tests pass cheaper ones.
    """

    def __init__(self, hasher: Argon2Hasher | None = None) -> None:
        self._hasher = hasher or Argon2Hasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """Return whether ``password`` matches ``password_hash``.

        Only a mismatch returns False. A malformed stored hash raises, because
        it is data corruption to investigate, not a wrong password.
        """
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False

    def verify_against_dummy(self, password: str) -> None:
        """Spend the time of a real verification when there is no account to check.

        Without it, a login for an unknown email answers measurably faster than
        one with a wrong password, which reveals which emails have accounts.
        """
        self.verify(self._dummy_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        """Whether the hash was made with parameters other than the current ones."""
        return self._hasher.check_needs_rehash(password_hash)

    @cached_property
    def _dummy_hash(self) -> str:
        # Computed on first use, not at import: hashing is deliberately slow.
        return self.hash(secrets.token_urlsafe(32))
