"""Answer read-only endpoints from the response cache, saying which way in ``X-Cache``."""

from collections.abc import Callable

from flask import Response, current_app
from pydantic import BaseModel

from app.extensions import get_redis
from app.services.cache import CacheParams, ResponseCache

CACHE_HEADER = "X-Cache"

CACHE_NOTE = (
    "Responses are cached for 10 minutes, and replaced as soon as the data is "
    "reseeded. The X-Cache header says whether a response came from the cache "
    "(HIT), was computed (MISS), or was computed because the cache was "
    "unavailable (BYPASS)."
)


def cached_json(name: str, params: CacheParams, compute: Callable[[], BaseModel]) -> Response:
    """The JSON body of ``compute()``, from the cache when it holds one for ``params``.

    ``params`` must hold every input the body depends on, already validated
    and normalized, so that equal requests share one entry. The cache is
    shared by every user, so the body must not depend on who asks.
    """
    result = ResponseCache(get_redis()).get_or_compute(
        name, params, lambda: compute().model_dump_json()
    )
    response = current_app.response_class(result.value, mimetype="application/json")
    response.headers[CACHE_HEADER] = result.status
    return response
