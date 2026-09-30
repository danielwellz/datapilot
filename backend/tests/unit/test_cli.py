import json
from pathlib import Path

from flask import Flask


def test_openapi_command_prints_the_document(app: Flask) -> None:
    result = app.test_cli_runner().invoke(args=["openapi"])

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["info"]["title"] == "DataPilot API"
    assert "/api/health" in document["paths"]


def test_openapi_command_writes_the_document_to_a_file(app: Flask, tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"

    result = app.test_cli_runner().invoke(args=["openapi", "--output", str(output)])

    assert result.exit_code == 0
    assert result.stdout == ""
    assert f"Wrote the OpenAPI document to {output}" in result.stderr
    assert "/api/ready" in json.loads(output.read_text())["paths"]
