import base64
import hashlib
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient

from app.api.docs import SWAGGER_UI_ASSETS
from app.api.spec import API_VERSION, spec


@pytest.fixture(autouse=True)
def fresh_document() -> Iterator[None]:
    # spectree caches the generated document on first use, which is right for a
    # server process but would let one test's app decide another test's document.
    vars(spec).pop("_spec", None)
    yield
    vars(spec).pop("_spec", None)


def document(client: FlaskClient) -> dict[str, Any]:
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    body: dict[str, Any] = response.get_json()
    return body


def test_openapi_document_describes_the_api(client: FlaskClient) -> None:
    doc = document(client)

    assert doc["openapi"].startswith("3.")
    assert doc["info"]["title"] == "DataPilot API"
    assert doc["info"]["version"] == API_VERSION


def test_openapi_document_leaves_out_the_documentation_routes(client: FlaskClient) -> None:
    paths = document(client)["paths"]

    assert "/api/openapi.json" not in paths
    assert "/api/docs" not in paths


def test_swagger_ui_page_loads_the_openapi_document(client: FlaskClient) -> None:
    response = client.get("/api/docs")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    page = response.get_data(as_text=True)
    assert "swagger-ui" in page
    assert 'url: "/api/openapi.json"' in page


def test_api_version_matches_the_backend_package_version() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"

    assert tomllib.loads(pyproject.read_text())["project"]["version"] == API_VERSION


def test_json_responses_tell_browsers_not_to_render_frame_or_sniff_them(
    client: FlaskClient,
) -> None:
    for response in (client.get("/api/health"), client.get("/api/missing")):
        assert response.headers["Content-Security-Policy"] == (
            "default-src 'none'; frame-ancestors 'none'"
        )
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "no-referrer"


def test_docs_page_policy_allows_its_inline_script_and_the_pinned_assets_only(
    client: FlaskClient,
) -> None:
    response = client.get("/api/docs")
    page = response.get_data(as_text=True)
    policy = response.headers["Content-Security-Policy"]

    (script,) = re.findall(r"<script>(.*?)</script>", page, re.DOTALL)
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src {SWAGGER_UI_ASSETS} 'sha256-{digest}';" in policy
    assert "frame-ancestors 'none'" in policy
    # If spectree moves to another Swagger UI version, the policy must follow.
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
    assert external
    assert all(url.startswith(SWAGGER_UI_ASSETS) for url in external)
