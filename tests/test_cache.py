import os
import os
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from cache import ResponseCache


def test_cache_round_trip(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    cache = ResponseCache(str(cache_file))
    key = ResponseCache.make_key("file.py", "content")
    cache.set(key, "summary")

    new_cache = ResponseCache(str(cache_file))
    assert new_cache.get(key) == "summary"


def test_cache_get_missing(tmp_path: Path) -> None:
    cache = ResponseCache(str(tmp_path / "cache.json"))
    assert cache.get("unknown") is None


def test_progress_tracking(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    cache = ResponseCache(str(cache_file))
    module_data = {"path": "mod.py", "summary": "s"}
    cache.mark_done("mod.py", module_data)

    new_cache = ResponseCache(str(cache_file))
    assert new_cache.get_progress() == {"mod.py": module_data}

    new_cache.clear_progress()
    assert new_cache.get_progress() == {}
