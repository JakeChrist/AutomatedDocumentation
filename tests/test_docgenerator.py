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
    from chunk_utils import get_tokenizer
    from docgenerator import _summarize_chunked

    tokenizer = get_tokenizer()
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


def test_chunking_accounts_for_prompt_overhead(tmp_path: Path) -> None:
    from cache import ResponseCache
    from chunk_utils import get_tokenizer
    from docgenerator import _summarize_chunked
    from llm_client import SYSTEM_PROMPT, PROMPT_TEMPLATES

    tokenizer = get_tokenizer()
    text = "word " * 15
    cache = ResponseCache(str(tmp_path / "cache.json"))
    template = PROMPT_TEMPLATES["module"]
    overhead = len(tokenizer.encode(SYSTEM_PROMPT)) + len(tokenizer.encode(template.format(text="")))
    max_context_tokens = overhead + 10

    with patch("docgenerator._summarize", return_value="summary") as mock_sum:
        _summarize_chunked(
            client=object(),
            cache=cache,
            key_prefix="k",
            text=text,
            prompt_type="module",
            tokenizer=tokenizer,
            max_context_tokens=max_context_tokens,
            chunk_token_budget=100,
        )
        assert mock_sum.call_count > 1


def test_merge_recurses_when_prompt_too_long(tmp_path: Path) -> None:
    from cache import ResponseCache
    from chunk_utils import get_tokenizer
    from docgenerator import _summarize_chunked
    from llm_client import SYSTEM_PROMPT, PROMPT_TEMPLATES

    tokenizer = get_tokenizer()
    text = "word " * 200
    cache = ResponseCache(str(tmp_path / "cache.json"))
    template = PROMPT_TEMPLATES["module"]
    overhead = len(tokenizer.encode(SYSTEM_PROMPT)) + len(
        tokenizer.encode(template.format(text=""))
    )
    max_context_tokens = overhead + 50

    def fake_sum(client, cache_obj, key, text_arg, prompt_type):
        template = PROMPT_TEMPLATES.get(prompt_type, PROMPT_TEMPLATES["module"])
        overhead = len(tokenizer.encode(SYSTEM_PROMPT)) + len(
            tokenizer.encode(template.format(text=""))
        )
        available = max_context_tokens - overhead
        assert len(tokenizer.encode(text_arg)) <= available
        if prompt_type == "module":
            return "summary " * 30
        return "short"

    with patch("docgenerator._summarize", side_effect=fake_sum) as mock_sum:
        _summarize_chunked(
            client=object(),
            cache=cache,
            key_prefix="k",
            text=text,
            prompt_type="module",
            tokenizer=tokenizer,
            max_context_tokens=max_context_tokens,
            chunk_token_budget=10,
        )
        merge_calls = [c for c in mock_sum.call_args_list if c.args[4] == "docstring"]
        assert len(merge_calls) > 1


def test_structured_chunker_keeps_functions_atomic(tmp_path: Path) -> None:
    from cache import ResponseCache
    from parser_python import parse_python_file
    from chunk_utils import get_tokenizer
    from docgenerator import _summarize_module_chunked
    from llm_client import SYSTEM_PROMPT, PROMPT_TEMPLATES

    src = (
        "def f1():\n"
        "    x = 1\n"
        + "    x += 1\n" * 5
        + "    return x\n\n"
        "def f2():\n"
        "    y = 1\n"
        + "    y += 1\n" * 5
        + "    return y\n"
    )
    file = tmp_path / "m.py"
    file.write_text(src)
    parsed = parse_python_file(str(file))

    tokenizer = get_tokenizer()
    cache = ResponseCache(str(tmp_path / "cache.json"))

    with patch("docgenerator._summarize", return_value="sum") as mock_sum:
        flen = len(tokenizer.encode(parsed["functions"][0]["source"]))
        budget = flen + 5
        overhead = len(tokenizer.encode(SYSTEM_PROMPT)) + len(tokenizer.encode(PROMPT_TEMPLATES["module"].format(text="")))
        _summarize_module_chunked(
            client=object(),
            cache=cache,
            key_prefix="k",
            module_text=src,
            module=parsed,
            tokenizer=tokenizer,
            max_context_tokens=overhead + budget,
            chunk_token_budget=budget,
        )

        chunks = [c.args[3] for c in mock_sum.call_args_list if c.args[4] == "module"]
        assert len(chunks) == 2
        func_sources = {f["source"] for f in parsed["functions"]}
        assert set(chunks) == func_sources


def test_structured_chunker_splits_large_class_by_method(tmp_path: Path) -> None:
    from cache import ResponseCache
    from parser_python import parse_python_file
    from chunk_utils import get_tokenizer
    from docgenerator import _summarize_module_chunked
    from llm_client import SYSTEM_PROMPT, PROMPT_TEMPLATES

    class_src = (
        "class Foo:\n"
        "    def a(self):\n"
        + "        x = 1\n"
        + "        x += 1\n" * 5
        + "        return x\n\n"
        "    def b(self):\n"
        + "        y = 1\n"
        + "        y += 1\n" * 5
        + "        return y\n"
    )
    file = tmp_path / "m.py"
    file.write_text(class_src)
    parsed = parse_python_file(str(file))

    tokenizer = get_tokenizer()
    cache = ResponseCache(str(tmp_path / "cache.json"))

    with patch("docgenerator._summarize", return_value="sum") as mock_sum:
        mlen = len(tokenizer.encode(parsed["classes"][0]["methods"][0]["source"]))
        budget = mlen + 5
        overhead = len(tokenizer.encode(SYSTEM_PROMPT)) + len(tokenizer.encode(PROMPT_TEMPLATES["module"].format(text="")))
        _summarize_module_chunked(
            client=object(),
            cache=cache,
            key_prefix="k",
            module_text=class_src,
            module=parsed,
            tokenizer=tokenizer,
            max_context_tokens=overhead + budget,
            chunk_token_budget=budget,
        )

        chunks = [c.args[3] for c in mock_sum.call_args_list if c.args[4] == "module"]
        methods = parsed["classes"][0]["methods"]
        method_sources = {m["source"] for m in methods}
        assert len(chunks) == len(methods)
        assert set(chunks) == method_sources


def test_subclass_methods_are_summarized(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "mod.py").write_text(
        "class A:\n    class B:\n        def m(self):\n            pass\n"
    )

    output_dir = tmp_path / "docs"

    with patch("docgenerator.LLMClient") as MockClient, patch(
        "docgenerator._summarize",
        return_value="summary",
    ) as mock_sum:
        instance = MockClient.return_value
        instance.ping.return_value = True
        ret = main([str(project_dir), "--output", str(output_dir)])
        assert ret == 0

    assert any("B:m" in call.args[2] for call in mock_sum.call_args_list)
