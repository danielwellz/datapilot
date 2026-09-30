"""Flask CLI commands, available as ``flask --app app <command>``."""

import json
from pathlib import Path
from typing import Any

import click
from flask import Flask

from app.api.spec import spec


def register_cli(app: Flask) -> None:
    app.cli.add_command(openapi_command)


@click.command("openapi")
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help="Write the document to this file instead of standard output.",
)
def openapi_command(output: Path | None) -> None:
    """Export the OpenAPI document as JSON, for example to generate client types."""
    document: dict[str, Any] = spec.spec
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if output is None:
        click.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        click.echo(f"Wrote the OpenAPI document to {output}", err=True)
