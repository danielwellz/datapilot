import runpy
from pathlib import Path

import pytest

CONFIG = Path(__file__).parents[2] / "gunicorn.conf.py"


@pytest.mark.parametrize("has_shared_memory", [True, False])
def test_worker_tmp_dir_uses_shared_memory_only_where_it_exists(
    monkeypatch: pytest.MonkeyPatch, has_shared_memory: bool
) -> None:
    monkeypatch.setattr(Path, "is_dir", lambda path: has_shared_memory)

    settings = runpy.run_path(str(CONFIG))

    expected = settings["_SHARED_MEMORY"] if has_shared_memory else None
    assert settings["worker_tmp_dir"] == expected
