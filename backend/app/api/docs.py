"""The OpenAPI document and the Swagger UI page that renders it."""

from typing import Any

from flask import Blueprint, Response, jsonify, url_for
from spectree.page import PAGE_TEMPLATES

from app.api.spec import spec

# spectree can serve these pages itself, but it leaves every route under its
# own path out of the document, and ours share the /api prefix with the API.
docs = Blueprint("docs", __name__)


@docs.get("/openapi.json")
def openapi_document() -> Response:
    document: dict[str, Any] = spec.spec
    return jsonify(document)


@docs.get("/docs")
def swagger_ui() -> str:
    template: str = PAGE_TEMPLATES["swagger"]
    return template.format(
        spec_url=url_for(".openapi_document"),
        spec_path="api/docs",
        **spec.config.swagger_oauth2_config(),
    )
