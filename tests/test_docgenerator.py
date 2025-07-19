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
    assert any(call.args[1] == "project" for call in instance.summarize.call_args_list)


def test_readme_summary_used(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "mod.py").write_text("def foo():\n    pass\n")
    (project_dir / "README.md").write_text("Project docs")

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient:
        instance = MockClient.return_value
        instance.ping.return_value = True
        instance.summarize.side_effect = lambda text, pt: f"{pt} summary"
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "readme summary" in html
    assert any(call.args[1] == "readme" for call in instance.summarize.call_args_list)


def test_clean_output_dir(tmp_path: Path) -> None:
    out = tmp_path / "docs"
    out.mkdir()
    generated = out / "old.html"
    generated.write_text("<!-- Generated by DocGen-LM -->\n<html></html>", encoding="utf-8")
    custom = out / "custom.html"
    custom.write_text("<html></html>", encoding="utf-8")
    asset = out / "style.css"
    asset.write_text("body {}", encoding="utf-8")

    from docgenerator import clean_output_dir

    clean_output_dir(str(out))

    assert not generated.exists()
    assert custom.exists()
    assert asset.exists()


def test_summarize_chunked_splits_long_text(tmp_path: Path) -> None:
    from cache import ResponseCache
    from docgenerator import _get_tokenizer, _summarize_chunked

    tokenizer = _get_tokenizer()
    text = "word " * 50
    cache = ResponseCache(str(tmp_path / "cache.json"))

    with patch("docgenerator._summarize", return_value="summary") as mock_sum:
        _summarize_chunked(
            client=object(),
            cache=cache,
            key_prefix="k",
            text=text,
            prompt_type="module",
            tokenizer=tokenizer,
            max_context_tokens=10,
            chunk_token_budget=5,
        )
        assert mock_sum.call_count > 1
