import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docgenerator import main


def test_subclass_docs_and_method_summary(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "mod.py").write_text(
        "class A:\n    class B:\n        def m(self):\n            pass\n"
    )

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.side_effect = lambda text, pt, **kwargs: f"{pt} summary"
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    html = (output_dir / "mod.html").read_text(encoding="utf-8")
    pos = html.find("<summary>Class: B")
    assert pos != -1
    assert html.find("docstring summary", pos) != -1
    method_pos = html.find("Method:")
    assert method_pos != -1 and html.find("docstring summary", method_pos) != -1
