"""Reference data for building filter controls."""

from flask import Blueprint
from spectree import Response

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
def filter_options() -> MetaOut:
    """Filter options for the orders explorer.

    Countries and categories present in the data, every status and channel,
    and the UTC dates of the oldest and newest order.
    """
    return MetaService(db.session()).filter_options()
