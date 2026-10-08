import re

import pytest

from app.services.cursors import MAX_CURSOR_LENGTH, CursorSigner, InvalidCursor

SECRET = b"test-secret-key"
PURPOSE = "test-cursor"


@pytest.fixture
def signer() -> CursorSigner:
    return CursorSigner(SECRET, PURPOSE)


def test_unsign_returns_the_signed_payload(signer: CursorSigner) -> None:
    payload = b'{"id":42,"key":"2026-01-01T00:00:00Z"}'

    assert signer.unsign(signer.sign(payload)) == payload


def test_cursor_is_url_safe_without_padding(signer: CursorSigner) -> None:
    cursor = signer.sign(b"a payload of a length that needs padding")

    assert re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", cursor)


def _replace_char(text: str, index: int) -> str:
    return text[:index] + ("A" if text[index] != "A" else "B") + text[index + 1 :]


def test_cursor_with_an_edited_payload_is_rejected(signer: CursorSigner) -> None:
    cursor = signer.sign(b'{"id":42}')

    with pytest.raises(InvalidCursor):
        signer.unsign(_replace_char(cursor, 0))


def test_cursor_with_an_edited_signature_is_rejected(signer: CursorSigner) -> None:
    cursor = signer.sign(b'{"id":42}')

    with pytest.raises(InvalidCursor):
        signer.unsign(_replace_char(cursor, len(cursor) - 2))


def test_cursor_signed_with_another_secret_is_rejected(signer: CursorSigner) -> None:
    cursor = CursorSigner(b"another-secret", PURPOSE).sign(b'{"id":42}')

    with pytest.raises(InvalidCursor):
        signer.unsign(cursor)


def test_cursor_signed_for_another_purpose_is_rejected(signer: CursorSigner) -> None:
    cursor = CursorSigner(SECRET, "another-purpose").sign(b'{"id":42}')

    with pytest.raises(InvalidCursor):
        signer.unsign(cursor)


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "no-separator",
        "payload.",
        ".signature",
        "pay load.signature",
        "payload.sig=",
        "a.b.c",
        "abcde.abcde",  # 4n + 1 characters cannot be base64
        "x" * (MAX_CURSOR_LENGTH + 1),
    ],
)
def test_malformed_cursor_is_rejected(signer: CursorSigner, cursor: str) -> None:
    with pytest.raises(InvalidCursor):
        signer.unsign(cursor)


def test_invalid_cursor_is_a_400_with_its_own_code() -> None:
    error = InvalidCursor()

    assert error.status == 400
    assert error.code == "invalid_cursor"
    assert "first page" in error.message
