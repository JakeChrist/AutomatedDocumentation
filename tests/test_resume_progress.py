import pytest
from pathlib import Path

import docgenerator
from cache import ResponseCache


def test_resume_progress(tmp_path, monkeypatch):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "mod1.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (project_dir / "mod2.py").write_text("def b():\n    return 2\n", encoding="utf-8")

    out_dir = tmp_path / "docs"

    module_calls = []

    def fake_summarize_module(client, cache, key_prefix, module_text, module, tokenizer, max_context_tokens, chunk_token_budget):
        path = key_prefix.split(":")[0]
        module_calls.append(path)
        return "summary"

    def fake_summarize_chunked(client, cache, key, text, prompt_type, max_context_tokens, chunk_token_budget):
        return "summary"

    def fake_rewrite_docstring(*args, **kwargs):
        return None

    monkeypatch.setattr(docgenerator, "_summarize_module_chunked", fake_summarize_module)
    monkeypatch.setattr(docgenerator, "_summarize_chunked", fake_summarize_chunked)
    monkeypatch.setattr(docgenerator, "_rewrite_docstring", fake_rewrite_docstring)
    monkeypatch.setattr(docgenerator.LLMClient, "ping", lambda self: True)

    original_set_progress = ResponseCache.set_progress_entry
    calls = {"count": 0}

    def crashing_set_progress(self, path, module_data):
        original_set_progress(self, path, module_data)
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(ResponseCache, "set_progress_entry", crashing_set_progress)

    with pytest.raises(RuntimeError):
        docgenerator.main(["--output", str(out_dir), str(project_dir)])

    cache = ResponseCache(str(out_dir / "cache.json"))
    progress = cache.get_progress()
    assert list(progress.keys()) == [str(project_dir / "mod1.py")]

    monkeypatch.setattr(ResponseCache, "set_progress_entry", original_set_progress)
    module_calls.clear()

    ret = docgenerator.main(["--output", str(out_dir), str(project_dir), "--resume"])
    assert ret == 0

    assert [Path(p).name for p in module_calls] == ["mod2.py"]
    assert (out_dir / "mod1.html").exists()
    assert (out_dir / "mod2.html").exists()

    cache2 = ResponseCache(str(out_dir / "cache.json"))
    assert cache2.get_progress() == {}
