"""Reference data for building filter controls."""

from flask import Blueprint
from flask import Response as FlaskResponse
from spectree import Response

from app.api.caching import cached_json
from app.api.security import BEARER_AUTH, require_access_token
from app.api.spec import spec
from app.extensions import db
from app.schemas.errors import ErrorOut
from app.schemas.meta import MetaOut
from app.services.meta import MetaService

meta = Blueprint("meta", __name__)


@meta.get("/meta")
@spec.validate(
    resp=Response(HTTP_200=MetaOut, HTTP_401=ErrorOut), tags=["meta"], security=BEARER_AUTH
)
@require_access_token
def filter_options() -> FlaskResponse:
    """Filter options for the orders explorer.

    Countries and categories present in the data, every status and channel,
    and the UTC dates of the oldest and newest order. Cached until the data
    is reseeded or for 10 minutes; `X-Cache` says HIT, MISS or BYPASS.
    """
    # The options depend on nothing but the data, which the key's data
    # version already identifies.
    return cached_json(
        "meta:filter-options", {}, lambda: MetaService(db.session()).filter_options()
    )
