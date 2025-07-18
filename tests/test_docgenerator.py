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
            "project summary",
            "class summary",
            "improved class doc",
            "function summary",
            "improved function doc",
        ]
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    html = (output_dir / "mod.html").read_text(encoding="utf-8")
    assert "improved class doc" in html
    assert "function summary" in html
    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "module summary" in index_html


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
            "project summary",
            "class summary",
        ]
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    html = (output_dir / "mod.html").read_text(encoding="utf-8")
    assert "class summary" in html


def test_project_summary_is_sanitized(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "mod.py").write_text("def foo():\n    pass\n")

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.side_effect = [
            "module summary",
            "project summary",
            "function summary",
            "improved function doc",
        ]
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "You can run this" not in html
    assert "It prints." in html


def test_readme_summary_used(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "mod.py").write_text("def foo():\n    pass\n")
    (project_dir / "README.md").write_text("Project docs")

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.side_effect = [
            "module summary",
            "readme summary",
            "project summary",
            "function summary",
            "improved function doc",
        ]
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "readme summary" in html
    assert any(
        args[1] == "readme" for args, _ in instance.summarize.call_args_list
    )
