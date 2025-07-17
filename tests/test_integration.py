import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from docgenerator import main


def test_docgenerator_generates_html(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    # simple python file
    (project_dir / "hello.py").write_text('def hi():\n    """Say hi."""\n    return "hi"\n')
    # simple matlab file
    (project_dir / "util.m").write_text('% util function\nfunction y = util(x)\n y = x;\nend\n')

    output_dir = tmp_path / "out"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.return_value = "summary"
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    # verify html files created
    assert (output_dir / "index.html").exists()
    assert (output_dir / "hello.html").exists()
    assert (output_dir / "util.html").exists()

    html = (output_dir / "hello.html").read_text(encoding="utf-8")
    assert "summary" in html


def test_static_copied_from_any_cwd(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "mod.py").write_text("pass\n")

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.return_value = "summary"
        monkeypatch.chdir(tmp_path)
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    assert (output_dir / "static" / "style.css").exists()
