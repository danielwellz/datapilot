"""Alembic environment, driven by the Flask app through Flask-Migrate.

Logging is deliberately not configured here: migrations run inside the
application (``flask db ...`` and the test harness), which already logs JSON
to stdout, and ``logging.config.fileConfig`` would replace that setup.
"""

import logging
from collections.abc import Iterable
from typing import Any

from alembic import context
from alembic.operations import MigrationScript
from alembic.runtime.migration import MigrationContext
from flask import current_app
from flask_sqlalchemy import SQLAlchemy

logger = logging.getLogger("alembic.env")

config = context.config
db: SQLAlchemy = current_app.extensions["migrate"].db
# The URL goes into the config parser, where "%" starts an interpolation.
config.set_main_option(
    "sqlalchemy.url", db.engine.url.render_as_string(hide_password=False).replace("%", "%%")
)


def skip_empty_autogenerate(
    context: MigrationContext,
    revision: str | Iterable[str | None] | Iterable[str],
    directives: list[MigrationScript],
) -> None:
    """Do not write a migration file when autogenerate finds no schema change."""
    if getattr(config.cmd_opts, "autogenerate", False):
        upgrade_ops = directives[0].upgrade_ops
        if upgrade_ops is not None and upgrade_ops.is_empty():
            directives[:] = []
            logger.info("No changes in schema detected.")


def run_migrations_offline() -> None:
    """Emit the migration SQL instead of running it (``flask db upgrade --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=db.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations against the application's database."""
    configure_args: dict[str, Any] = current_app.extensions["migrate"].configure_args
    configure_args.setdefault("process_revision_directives", skip_empty_autogenerate)

    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=db.metadata, **configure_args)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
