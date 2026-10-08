"""Login credentials of the read-only role that runs Ask your data queries.

The migrations create ``datapilot_readonly`` without a password, so no secret
is ever committed. This module gives it one, taken from the connection string
the application will use (READONLY_DATABASE_URL).
"""

from typing import Any

from psycopg import Connection, sql
from sqlalchemy.engine import make_url

READONLY_ROLE = "datapilot_readonly"


class ReadonlyRoleError(ValueError):
    """The read-only connection string cannot be used to set the role's password."""


def set_readonly_role_password(connection: Connection[Any], readonly_url: str) -> None:
    """Allow ``datapilot_readonly`` to log in with the password in ``readonly_url``.

    The password is hashed (SCRAM-SHA-256) on this side of the connection, so
    the plain text never reaches the server, where statement logging could
    record it. The caller commits.
    """
    url = make_url(readonly_url)
    if url.username != READONLY_ROLE:
        raise ReadonlyRoleError(
            f"READONLY_DATABASE_URL must connect as {READONLY_ROLE}, not {url.username!r}"
        )
    if not url.password:
        raise ReadonlyRoleError("READONLY_DATABASE_URL has no password")

    verifier = connection.pgconn.encrypt_password(
        url.password.encode(), READONLY_ROLE.encode(), b"scram-sha-256"
    )
    connection.execute(
        sql.SQL("ALTER ROLE {role} WITH LOGIN PASSWORD {password}").format(
            role=sql.Identifier(READONLY_ROLE), password=sql.Literal(verifier.decode())
        )
    )
