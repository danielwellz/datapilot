import re
from pathlib import Path

import pytest

from app.analytics.queries import LOADED, SQL_DIR

SQL_FILES = sorted(SQL_DIR.glob("*.sql"))


def test_every_sql_file_is_loaded_and_every_loaded_query_has_a_file() -> None:
    assert {path.stem for path in SQL_FILES} == set(LOADED)


@pytest.mark.parametrize("path", SQL_FILES, ids=[path.name for path in SQL_FILES])
def test_each_query_starts_with_a_header_comment(path: Path) -> None:
    header = path.read_text(encoding="utf-8").splitlines()[0]

    # A title, a colon, then what the query returns.
    assert re.fullmatch(r"-- [A-Z].+: .+", header), header


@pytest.mark.parametrize("name", sorted(LOADED))
def test_queries_take_values_only_as_named_bind_parameters(name: str) -> None:
    text = (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")

    # No placeholders a Python formatter could fill in, and at least one bind.
    assert not re.search(r"%\(|%s|\{\w*\}", text)
    assert LOADED[name].compile().binds
