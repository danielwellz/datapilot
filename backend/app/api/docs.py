"""The OpenAPI document and the Swagger UI page that renders it."""

import base64
import hashlib
import re
from typing import Any

from flask import Blueprint, Response, jsonify, make_response, url_for
from spectree.page import PAGE_TEMPLATES

from app.api.spec import spec

# spectree can serve these pages itself, but it leaves every route under its
# own path out of the document, and ours share the /api prefix with the API.
docs = Blueprint("docs", __name__)

# The page loads Swagger UI from this pinned CDN path (spectree's template),
# and nothing else from outside; a test checks the template still agrees.
SWAGGER_UI_ASSETS = "https://unpkg.com/swagger-ui-dist@5.11.0/"
_INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.DOTALL)


@docs.get("/openapi.json")
def openapi_document() -> Response:
    document: dict[str, Any] = spec.spec
    return jsonify(document)


@docs.get("/docs")
def swagger_ui() -> Response:
    template: str = PAGE_TEMPLATES["swagger"]
    page = template.format(
        spec_url=url_for(".openapi_document"),
        spec_path="api/docs",
        **spec.config.swagger_oauth2_config(),
    )
    response = make_response(page)
    response.headers["Content-Security-Policy"] = docs_page_policy(page)
    return response


def docs_page_policy(page: str) -> str:
    """A policy that allows the page's own inline script, by hash, and the pinned assets."""
    script_hashes = " ".join(
        f"'sha256-{_sha256_base64(script)}'" for script in _INLINE_SCRIPT.findall(page)
    )
    return "; ".join(
        (
            "default-src 'none'",
            f"script-src {SWAGGER_UI_ASSETS} {script_hashes}",
            # Swagger UI sets style attributes as it renders.
            f"style-src {SWAGGER_UI_ASSETS} 'unsafe-inline'",
            "img-src 'self' data:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "form-action 'none'",
        )
    )


def _sha256_base64(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
