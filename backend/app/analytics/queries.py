"""The analytics SQL, read from ``sql/*.sql`` once when this module is imported.

Each query is a file of its own, so it can be read, formatted and run in
``psql`` as it is. Values reach the queries only as named bind parameters
(``:start_at``); nothing is ever formatted into the SQL text.
"""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from sqlalchemy import TextClause, text

SQL_DIR = Path(__file__).resolve().parent / "sql"

_loaded: dict[str, TextClause] = {}


def _load(name: str) -> TextClause:
    clause = text((SQL_DIR / f"{name}.sql").read_text(encoding="utf-8"))
    _loaded[name] = clause
    return clause


# A missing or misnamed file fails at import, not on the first request.
SUMMARY = _load("summary")
REVENUE_MONTHLY = _load("revenue_monthly")
TOP_CUSTOMERS = _load("top_customers")
PRODUCT_RANKING = _load("product_ranking")
COHORTS = _load("cohorts")

LOADED: Mapping[str, TextClause] = MappingProxyType(_loaded)
"""Every loaded query by file name, so a test can prove no file is left unused."""
