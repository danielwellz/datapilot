"""Opaque, tamper-evident pagination cursors.

A cursor records where the previous page ended, and the client hands it back
unchanged. It is signed with HMAC-SHA256, so the server can tell a cursor it
issued from one that was edited or made up, and encoded as URL-safe base64,
so it fits in a query string. Clients must treat it as opaque, which leaves
its contents free to change between releases.
"""

import base64
import binascii
import hashlib
import hmac
import re

from app.errors import BadRequest

# Far above any cursor this API issues; checked before any decoding work.
MAX_CURSOR_LENGTH = 512

_URLSAFE_BASE64 = re.compile(r"[A-Za-z0-9_-]+")


class InvalidCursor(BadRequest):
    code = "invalid_cursor"
    default_message = (
        "The cursor is invalid or belongs to a different query. Start again from the first page."
    )


class CursorSigner:
    """Signs cursor payloads and verifies the cursors clients send back."""

    def __init__(self, secret: bytes, purpose: str) -> None:
        # A key derived per purpose: a signature made for one kind of cursor,
        # or by anything else keyed with the application secret, never
        # verifies as another.
        self._key = hmac.new(secret, purpose.encode(), hashlib.sha256).digest()

    def sign(self, payload: bytes) -> str:
        return f"{_encode(payload)}.{_encode(self._tag(payload))}"

    def unsign(self, cursor: str) -> bytes:
        """Return the payload of a cursor this signer issued, or raise ``InvalidCursor``."""
        if len(cursor) > MAX_CURSOR_LENGTH:
            raise InvalidCursor()
        encoded_payload, _, encoded_tag = cursor.partition(".")
        payload = _decode(encoded_payload)
        if not hmac.compare_digest(_decode(encoded_tag), self._tag(payload)):
            raise InvalidCursor()
        return payload

    def _tag(self, payload: bytes) -> bytes:
        return hmac.new(self._key, payload, hashlib.sha256).digest()


def _encode(data: bytes) -> str:
    # Padding is dropped: "=" would need escaping in a query string.
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(text: str) -> bytes:
    # The decoder silently skips characters outside the alphabet; checking
    # first makes every malformed cursor fail the same, explicit way.
    if not _URLSAFE_BASE64.fullmatch(text):
        raise InvalidCursor()
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except binascii.Error as error:  # a length no encoder produces, such as 4n + 1
        raise InvalidCursor() from error
