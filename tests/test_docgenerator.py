import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docgenerator import main


def test_skips_invalid_python_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    # file with invalid syntax due to leading zero
    (project_dir / "bad.py").write_text("x = 08\n")

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.return_value = "summary"
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    # only index page should be generated
    assert (output_dir / "index.html").exists()
    assert not (output_dir / "bad.html").exists()


def test_generates_class_and_function_summaries(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "mod.py").write_text(
        'class Foo:\n    """Doc"""\n    pass\n\n' "def bar():\n    return 1\n"
    )

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.side_effect = [
            "module summary",
            "class summary",
            "function summary",
            "project summary",
        ]
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    html = (output_dir / "mod.html").read_text(encoding="utf-8")
    assert "class summary" in html
    assert "function summary" in html


def test_skips_non_utf8_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "bad.py").write_bytes(b"\xff\xfe\xfd")

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.return_value = "summary"
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    assert (output_dir / "index.html").exists()
    assert not (output_dir / "bad.html").exists()


def test_handles_class_without_docstring(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "mod.py").write_text("class Foo:\n    pass\n")

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.side_effect = [
            "module summary",
            "class summary",
            "project summary",
        ]
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    html = (output_dir / "mod.html").read_text(encoding="utf-8")
    assert "class summary" in html
