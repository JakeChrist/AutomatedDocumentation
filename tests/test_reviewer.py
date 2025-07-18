import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reviewer import main
from html_writer import write_module_page, write_index


def _make_module(tmp_path: Path, summary: str, methods=None) -> Path:
    data = {
        "name": "mod",
        "summary": summary,
        "classes": [],
        "functions": [],
    }
    if methods is not None:
        data["classes"] = [
            {"name": "Foo", "docstring": "", "summary": "", "methods": methods}
        ]
    write_module_page(str(tmp_path), data, [("index", "index.html")])
    return tmp_path / "mod.html"


def test_assistant_phrasing_detected(tmp_path: Path, capsys) -> None:
    _make_module(tmp_path, "You can use this class.")
    main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "[ASSISTANT]" in out
    assert "mod.html" in out


def test_contradiction_detected(tmp_path: Path, capsys) -> None:
    methods = [{"name": "bar", "signature": "def bar()", "docstring": "", "source": ""}]
    _make_module(tmp_path, "No methods defined", methods)
    main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "[CONTRADICTION]" in out


def test_hallucination_detected(tmp_path: Path, capsys) -> None:
    _make_module(tmp_path, "Implements tic-tac-toe features")
    main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "[HALLUCINATION]" in out


def test_autofix_removes_phrasing(tmp_path: Path) -> None:
    html_path = _make_module(tmp_path, "You can call this.")
    main([str(tmp_path), "--autofix"])
    html = html_path.read_text(encoding="utf-8")
    assert "You can" not in html
