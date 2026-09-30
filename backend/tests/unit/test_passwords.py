import time

import pytest
from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import InvalidHashError

from app.services.passwords import PasswordHasher

PASSWORD = "correct horse battery"


@pytest.fixture(scope="module")
def hasher() -> PasswordHasher:
    return PasswordHasher()


def test_hash_is_argon2id_and_never_contains_the_password(hasher: PasswordHasher) -> None:
    password_hash = hasher.hash(PASSWORD)

    assert password_hash.startswith("$argon2id$")
    assert PASSWORD not in password_hash


def test_hashing_the_same_password_twice_uses_different_salts(hasher: PasswordHasher) -> None:
    assert hasher.hash(PASSWORD) != hasher.hash(PASSWORD)


def test_verify_accepts_the_right_password(hasher: PasswordHasher) -> None:
    assert hasher.verify(hasher.hash(PASSWORD), PASSWORD) is True


def test_verify_rejects_a_wrong_password(hasher: PasswordHasher) -> None:
    assert hasher.verify(hasher.hash(PASSWORD), PASSWORD.upper()) is False


def test_verify_raises_on_a_corrupted_hash_instead_of_reporting_a_mismatch(
    hasher: PasswordHasher,
) -> None:
    with pytest.raises(InvalidHashError):
        hasher.verify("not-an-argon2-hash", PASSWORD)


def test_hash_made_with_other_parameters_needs_rehash(hasher: PasswordHasher) -> None:
    weak = PasswordHasher(Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1))

    assert hasher.needs_rehash(weak.hash(PASSWORD)) is True
    assert hasher.needs_rehash(hasher.hash(PASSWORD)) is False


def test_dummy_verification_takes_about_as_long_as_a_real_one(hasher: PasswordHasher) -> None:
    real_hash = hasher.hash(PASSWORD)
    hasher.verify_against_dummy(PASSWORD)  # computes the dummy hash outside the timing

    started = time.perf_counter()
    hasher.verify(real_hash, "wrong password")
    real = time.perf_counter() - started
    started = time.perf_counter()
    hasher.verify_against_dummy("wrong password")
    dummy = time.perf_counter() - started

    # Same algorithm and parameters, so the same cost; the bounds are loose
    # enough to survive a busy CI machine and still catch a skipped check.
    assert dummy > real / 3
