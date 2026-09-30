"""Operational endpoints: liveness and readiness probes."""

from flask import Blueprint
from spectree import Response

from app.api.spec import spec
from app.errors import ServiceUnavailable
from app.extensions import db, get_redis
from app.schemas.errors import ErrorOut
from app.schemas.health import HealthOut, ReadinessOut
from app.services.health import check_readiness

system = Blueprint("system", __name__)


@system.get("/health")
@spec.validate(resp=Response(HTTP_200=HealthOut), tags=["system"])
def health() -> HealthOut:
    """Liveness probe.

    Answers as long as the process can serve requests. It checks no
    dependencies, so an outage of PostgreSQL or Redis never gets the
    process restarted.
    """
    return HealthOut(status="ok")


@system.get("/ready")
@spec.validate(resp=Response(HTTP_200=ReadinessOut, HTTP_503=ErrorOut), tags=["system"])
def ready() -> ReadinessOut:
    """Readiness probe.

    Checks PostgreSQL (`SELECT 1`) and Redis (`PING`). Answers 503 with the
    result of each check when either fails, so traffic is held back until
    both are reachable.
    """
    report = check_readiness(db.engine, get_redis())
    if not report.ready:
        raise ServiceUnavailable(
            "A required service is unavailable.",
            details=[{"check": name, "status": status} for name, status in report.checks.items()],
        )
    return ReadinessOut(status="ok", checks=dict.fromkeys(report.checks, "ok"))
