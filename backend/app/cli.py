"""Flask CLI commands, available as ``flask --app app <command>``."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import click
import psycopg
from flask import Flask
from flask.cli import with_appcontext

from app import clock
from app.api.spec import spec
from app.config import current_settings
from app.extensions import db, get_redis
from app.seed.calendar import history_start
from app.seed.generator import SCALES
from app.services.db_roles import ReadonlyRoleError, set_readonly_role_password
from app.services.passwords import PasswordHasher
from app.services.seeding import DEMO_EMAIL, SeedReport, SeedService

_KIB = 1024


def register_cli(app: Flask) -> None:
    app.cli.add_command(openapi_command)
    app.cli.add_command(seed_command)
    app.cli.add_command(db_roles_command)


@click.command("openapi")
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help="Write the document to this file instead of standard output.",
)
# The document is built from the routes of the current app, so it needs one.
@with_appcontext
def openapi_command(output: Path | None) -> None:
    """Export the OpenAPI document as JSON, for example to generate client types."""
    document: dict[str, Any] = spec.spec
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if output is None:
        click.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        click.echo(f"Wrote the OpenAPI document to {output}", err=True)


@click.command("seed")
@click.option(
    "--scale",
    type=click.Choice(list(SCALES)),
    default="small",
    show_default=True,
    help="Dataset size: small for development and CI, full for performance work.",
)
@click.option(
    "--seed",
    "seed_value",
    type=click.IntRange(min=0),
    default=42,
    show_default=True,
    help="Random seed; the same seed and end date always give the same data.",
)
@click.option(
    "--end-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="The history covers the three years before this day.  [default: today (UTC)]",
)
@click.option(
    "--if-empty",
    is_flag=True,
    help="Load only when there are no orders yet; otherwise do nothing (for start-up jobs).",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Confirm replacing existing sales data in production.",
)
@with_appcontext
def seed_command(
    scale: str, seed_value: int, end_date: datetime | None, if_empty: bool, yes: bool
) -> None:
    """Replace the sales data with a generated dataset and create the demo account."""
    service = SeedService(db.session(), get_redis(), PasswordHasher())
    if service.has_sales_data():
        if if_empty:
            click.echo("Sales data is already loaded; nothing to do.")
            return
        if current_settings().is_production and not yes:
            raise click.ClickException(
                "This production database already holds sales data, and seeding "
                "replaces all of it. Pass --yes to replace it."
            )
    chosen = SCALES[scale]
    end = end_date.date() if end_date is not None else clock.utc_today()
    click.echo(
        f"Seeding the {chosen.name} dataset ({chosen.orders:,} orders, seed {seed_value}).",
        err=True,
    )
    report = service.seed(
        chosen,
        seed=seed_value,
        end_date=end,
        on_progress=ProgressPrinter(chosen.orders),
    )
    click.echo(format_seed_report(report))


class ProgressPrinter:
    """Prints loading progress in steps of 10%, so a long seed shows it is alive."""

    def __init__(self, total: int) -> None:
        self._total = total
        self._printed_step = 0

    def __call__(self, loaded: int) -> None:
        step = loaded * 10 // self._total
        if step > self._printed_step:
            self._printed_step = step
            click.echo(f"  {loaded:>9,} orders loaded ({step * 10}%)", err=True)


def format_seed_report(report: SeedReport) -> str:
    first_day = history_start(report.end_date)
    last_day: date = report.end_date - timedelta(days=1)
    demo = "created" if report.demo_account_created else "already existed, left unchanged"
    lines = [
        f"Seeded the {report.scale.name} dataset with seed {report.seed}, "
        f"history {first_day} to {last_day}, in {report.elapsed_seconds:.1f} s.",
        "",
        f"  {'table':<12} {'rows':>11} {'size':>10}",
        *(
            f"  {stats.table:<12} {stats.rows:>11,} {format_size(stats.total_bytes):>10}"
            for stats in report.tables
        ),
        "",
        f"Demo account {DEMO_EMAIL}: {demo}.",
        f"Data version: {report.data_version}.",
    ]
    return "\n".join(lines)


def format_size(size_bytes: int) -> str:
    """Binary units, as PostgreSQL's pg_size_pretty uses: 24576 -> "24 kB"."""
    if size_bytes < _KIB * _KIB:
        return f"{size_bytes / _KIB:.0f} kB"
    if size_bytes < _KIB**3:
        return f"{size_bytes / _KIB**2:.1f} MB"
    return f"{size_bytes / _KIB**3:.2f} GB"


@click.command("db-roles")
@with_appcontext
def db_roles_command() -> None:
    """Let the read-only role log in with the password in READONLY_DATABASE_URL.

    Run it after the migrations, which create the role without a password.
    """
    connection = db.engine.raw_connection()
    try:
        # The engine is built on psycopg, so the driver connection is one.
        driver_connection = cast("psycopg.Connection[Any]", connection.driver_connection)
        set_readonly_role_password(driver_connection, str(current_settings().readonly_database_url))
        connection.commit()
    except ReadonlyRoleError as error:
        raise click.ClickException(str(error)) from error
    except psycopg.errors.UndefinedObject as error:
        raise click.ClickException(
            "The read-only role does not exist yet; run the migrations first (make db-upgrade)."
        ) from error
    finally:
        connection.close()
    click.echo("The read-only role can now log in with the password in READONLY_DATABASE_URL.")
