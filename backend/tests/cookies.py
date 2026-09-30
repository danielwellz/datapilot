"""Read the Set-Cookie headers of a test response."""

from http.cookies import Morsel, SimpleCookie
from typing import Any

REFRESH_COOKIE = "refresh_token_cookie"
CSRF_COOKIE = "csrf_refresh_token"


def set_cookie(response: Any, name: str) -> Morsel[str]:
    """The cookie ``name`` as set by ``response``; fails if it was not set exactly once."""
    matches = [
        header for header in response.headers.getlist("Set-Cookie") if header.startswith(f"{name}=")
    ]
    assert len(matches) == 1, f"expected one Set-Cookie for {name}, got {matches}"
    cookie: SimpleCookie = SimpleCookie()
    cookie.load(matches[0])
    return cookie[name]
