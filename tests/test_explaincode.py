from pathlib import Path
from typing import Iterable
import importlib
import textwrap
import logging
import sys
import time

import pytest
from bs4 import BeautifulSoup

import explaincode
from explaincode import main
from cache import ResponseCache


def _create_fixture(tmp_path: Path) -> None:
    nested = tmp_path / "subdir" / "nested"
    nested.mkdir(parents=True)
    (nested / "page.html").write_text(
        "<html><body><h1>Overview</h1></body></html>", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Demo\n\nUsage: run it", encoding="utf-8")
    (tmp_path / "sample.json").write_text("{\"input\": \"data\"}", encoding="utf-8")


def _mock_llm_client() -> object:
    class Dummy:
        def summarize(self, text: str, prompt_type: str, system_prompt: str = "") -> str:  # pragma: no cover - simple stub
            return textwrap.dedent(
                """
                Overview: Demo project
                Purpose & Problem Solving: Solves a problem
                How to Run: Execute it
                Inputs: Input data
                Outputs: Output data
                System Requirements: None
                Examples: Example usage
                """
            ).strip()

    return Dummy()


def test_html_summary_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_fixture(tmp_path)
    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    main(["--path", str(tmp_path)])
    assert (tmp_path / "user_manual.html").exists()


def test_pdf_summary_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if importlib.util.find_spec("reportlab") is None:
        pytest.skip("reportlab not installed")
    _create_fixture(tmp_path)
    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    main(["--path", str(tmp_path), "--output-format", "pdf"])
    assert (tmp_path / "user_manual.pdf").exists()


def test_graceful_missing_docx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _create_fixture(tmp_path)
    try:
        from docx import Document
    except Exception:  # pragma: no cover - dependency missing
        Document = None  # type: ignore
    if Document:
        doc = Document()
        doc.add_paragraph("hi")
        doc.save(tmp_path / "guide.docx")
    monkeypatch.setattr(explaincode, "Document", None)
    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    main(["--path", str(tmp_path)])
    assert (tmp_path / "user_manual.html").exists()


def test_custom_output_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_fixture(tmp_path)
    out_dir = tmp_path / "dist"
    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    main(["--path", str(tmp_path), "--output", str(out_dir)])
    assert (out_dir / "user_manual.html").exists()


def test_collect_docs_filters(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "keep.md").write_text("hi", encoding="utf-8")
    (tmp_path / "docs" / "skip.txt").write_text("no", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme", encoding="utf-8")
    (tmp_path / "extra.md").write_text("extra", encoding="utf-8")
    files = explaincode.collect_docs(tmp_path)
    names = {f.name for f in files}
    assert "keep.md" in names and "skip.txt" not in names


def test_detect_placeholders() -> None:
    text = "Overview: [[NEEDS_OVERVIEW]]\nInputs: data\nOutputs: [[NEEDS_OUTPUTS]]"
    missing = explaincode.detect_placeholders(text)
    assert set(missing) == {"Overview", "Outputs"}




def test_full_docs_no_code_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _create_fixture(tmp_path)
    tracker = {"rank": 0, "extract": 0}

    def fake_rank(root: Path, patterns: list[str]) -> list[Path]:
        tracker["rank"] += 1
        return [tmp_path / "a.py"]

    def fake_extract(
        files: Iterable[Path], *, max_files: int, time_budget: int, max_bytes: int
    ) -> dict[Path, str]:
        tracker["extract"] += 1
        return {}

    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    monkeypatch.setattr(explaincode, "rank_code_files", fake_rank)
    monkeypatch.setattr(explaincode, "extract_snippets", fake_extract)

    caplog.set_level(logging.INFO)
    main(["--path", str(tmp_path), "--scan-code-if-needed"])
    assert tracker["rank"] == 0
    assert tracker["extract"] == 0
    log = caplog.text
    assert "DOC PASS" in log
    assert "Code scan skipped" in log


def test_missing_run_triggers_code_fallback_with_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "README.md").write_text("Only overview", encoding="utf-8")

    class Dummy:
        def __init__(self) -> None:
            self.calls = 0

        def summarize(self, text: str, prompt_type: str, system_prompt: str = "") -> str:
            self.calls += 1
            if self.calls == 1:
                return "Overview: x\\nHow to Run: [[NEEDS_RUN_INSTRUCTIONS]]"
            return "Overview: x\\nHow to Run: use it"

    paths = [tmp_path / f"f{i}.py" for i in range(3)]
    tracker: dict[str, object] = {"rank": 0, "extract": 0}

    def fake_rank(root: Path, patterns: list[str]) -> list[Path]:
        tracker["rank"] += 1
        return paths

    def fake_extract(
        files: Iterable[Path], *, max_files: int, time_budget: int, max_bytes: int
    ) -> dict[Path, str]:
        tracker["extract"] += 1
        lst = list(files)
        tracker["kwargs"] = {"max_files": max_files, "time_budget": time_budget}
        tracker["scanned"] = lst[:max_files]
        return {p: "code" for p in lst[:max_files]}

    monkeypatch.setattr(explaincode, "LLMClient", lambda: Dummy())
    monkeypatch.setattr(explaincode, "rank_code_files", fake_rank)
    monkeypatch.setattr(explaincode, "extract_snippets", fake_extract)

    caplog.set_level(logging.INFO)
    main(
        [
            "--path",
            str(tmp_path),
            "--scan-code-if-needed",
            "--max-code-files",
            "1",
            "--code-time-budget-seconds",
            "5",
        ]
    )
    html = (tmp_path / "user_manual.html").read_text(encoding="utf-8")
    assert "NEEDS_RUN_INSTRUCTIONS" not in html
    assert tracker["rank"] == 1
    assert tracker["extract"] == 1
    assert tracker["kwargs"] == {"max_files": 1, "time_budget": 5}
    assert len(tracker["scanned"]) == 1
    log = caplog.text
    assert "Pass 1 missing sections: How to Run" in log
    assert "Code scan triggered" in log


def test_no_code_flag_skips_code_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "README.md").write_text("Only overview", encoding="utf-8")

    class Dummy:
        def summarize(
            self, text: str, prompt_type: str, system_prompt: str = ""
        ) -> str:
            return "Overview: x\\nHow to Run: [[NEEDS_RUN_INSTRUCTIONS]]"

    tracker = {"rank": 0, "extract": 0}

    def fake_rank(root: Path, patterns: list[str]) -> list[Path]:
        tracker["rank"] += 1
        return []

    def fake_extract(
        files: Iterable[Path], *, max_files: int, time_budget: int, max_bytes: int
    ) -> dict[Path, str]:
        tracker["extract"] += 1
        return {}

    monkeypatch.setattr(explaincode, "LLMClient", lambda: Dummy())
    monkeypatch.setattr(explaincode, "rank_code_files", fake_rank)
    monkeypatch.setattr(explaincode, "extract_snippets", fake_extract)

    caplog.set_level(logging.INFO)
    main(["--path", str(tmp_path), "--scan-code-if-needed", "--no-code"])
    assert tracker["rank"] == 0
    assert tracker["extract"] == 0
    log = caplog.text
    assert "Code scan skipped: --no-code specified" in log
    assert "Unresolved placeholders: How to Run" in log


def test_force_code_flag_triggers_code_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _create_fixture(tmp_path)
    tracker = {"rank": 0, "extract": 0}

    def fake_rank(root: Path, patterns: list[str]) -> list[Path]:
        tracker["rank"] += 1
        return [tmp_path / "script.py"]

    def fake_extract(
        files: Iterable[Path], *, max_files: int, time_budget: int, max_bytes: int
    ) -> dict[Path, str]:
        tracker["extract"] += 1
        return {next(iter(files)): "code"}

    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    monkeypatch.setattr(explaincode, "rank_code_files", fake_rank)
    monkeypatch.setattr(explaincode, "extract_snippets", fake_extract)

    caplog.set_level(logging.INFO)
    main(["--path", str(tmp_path), "--force-code"])
    assert tracker["rank"] == 1
    assert tracker["extract"] == 1
    log = caplog.text
    assert "Code scan triggered: --force-code enabled" in log
    assert "Pass 1 complete: no sections missing" in log


def test_custom_title_and_filename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_fixture(tmp_path)
    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    main(["--path", str(tmp_path), "--title", "Fancy Guide"])
    out_file = tmp_path / "fancy_guide.html"
    assert out_file.exists()
    assert "<h1>Fancy Guide</h1>" in out_file.read_text(encoding="utf-8")


def test_insert_into_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_fixture(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    index = out_dir / "index.html"
    index.write_text("<html><body><ul></ul></body></html>", encoding="utf-8")
    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    main(["--path", str(tmp_path), "--output", str(out_dir), "--insert-into-index"])
    html = index.read_text(encoding="utf-8")
    assert '<a href="user_manual.html">User Manual</a>' in html


def test_docs_index_default_and_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_fixture(tmp_path)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.html").write_text("<html><body><nav></nav></body></html>", encoding="utf-8")
    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    main(["--path", str(tmp_path), "--insert-into-index"])
    manual = docs_dir / "user_manual.html"
    assert manual.exists()
    soup = BeautifulSoup((docs_dir / "index.html").read_text(encoding="utf-8"), "html.parser")
    nav = soup.find("nav")
    assert nav is not None
    first = nav.find("a")
    assert first and first["href"] == "user_manual.html"


def test_insert_into_root_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_fixture(tmp_path)
    (tmp_path / "index.html").write_text("<html><body><nav></nav></body></html>", encoding="utf-8")
    monkeypatch.setattr(explaincode, "LLMClient", _mock_llm_client)
    main(["--path", str(tmp_path), "--insert-into-index"])
    manual = tmp_path / "docs" / "user_manual.html"
    assert manual.exists()
    soup = BeautifulSoup((tmp_path / "index.html").read_text(encoding="utf-8"), "html.parser")
    nav = soup.find("nav")
    assert nav is not None
    first = nav.find("a")
    assert first and first["href"] == "docs/user_manual.html"


def test_chunking_triggers_multiple_calls_and_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paragraph1 = "aaa " * 2000
    paragraph2 = "bbb " * 2000
    text = "\n\n".join([paragraph1, paragraph2])

    class Dummy:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def summarize(self, text: str, prompt_type: str, system_prompt: str = "") -> str:
            self.calls.append(
                {"text": text, "prompt_type": prompt_type, "system_prompt": system_prompt}
            )
            if system_prompt == explaincode.MERGE_SYSTEM_PROMPT:
                return "final"
            return text.split()[0]

    client = Dummy()
    cache = ResponseCache(str(tmp_path / "cache.json"))
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, force=True)
    result = explaincode._summarize_manual(
        client, cache, text, chunking="auto", source="src"
    )

    assert result == "final"
    assert len(client.calls) == 3
    chunk_calls = client.calls[:-1]
    merge_call = client.calls[-1]
    assert all(c["system_prompt"] == explaincode.CHUNK_SYSTEM_PROMPT for c in chunk_calls)
    assert merge_call["system_prompt"] == explaincode.MERGE_SYSTEM_PROMPT
    assert merge_call["text"] == "aaa\n\nbbb"

    out = capsys.readouterr().out
    assert "Chunk 1/2 from src" in out
    assert "Merged LLM response length" in out


def test_chunk_edit_hook_applied(tmp_path: Path) -> None:
    paragraph1 = "aaa " * 2000
    paragraph2 = "bbb " * 2000
    text = "\n\n".join([paragraph1, paragraph2])

    class Dummy:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def summarize(self, text: str, prompt_type: str, system_prompt: str = "") -> str:
            self.calls.append(
                {"text": text, "prompt_type": prompt_type, "system_prompt": system_prompt}
            )
            if system_prompt == explaincode.MERGE_SYSTEM_PROMPT:
                return "final"
            return text.split()[0]

    def hook(chunks: list[str]) -> list[str]:
        return [c.upper() for c in chunks]

    client = Dummy()
    cache = ResponseCache(str(tmp_path / "cache.json"))
    result = explaincode._summarize_manual(
        client, cache, text, chunking="auto", source="src", post_chunk_hook=hook
    )

    assert result == "final"
    assert client.calls[-1]["text"] == "AAA\n\nBBB"


def test_parallel_chunk_summarization(tmp_path: Path) -> None:
    paragraph = "word " * 2000
    text = "\n\n".join([paragraph, paragraph])
    delay = 0.2

    class SlowClient:
        def summarize(self, text: str, prompt_type: str, system_prompt: str = "") -> str:
            if system_prompt == explaincode.CHUNK_SYSTEM_PROMPT:
                time.sleep(delay)
            return "ok"

    client = SlowClient()
    cache = ResponseCache(str(tmp_path / "cache.json"))
    start = time.perf_counter()
    explaincode._summarize_manual(client, cache, text, chunking="auto", source="src")
    duration = time.perf_counter() - start
    assert duration < delay * 1.5


def test_hierarchical_merge_logged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    big = "word " * 5000
    text = "\n\n".join([big, big])

    class Dummy:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def summarize(self, text: str, prompt_type: str, system_prompt: str = "") -> str:
            self.calls.append(
                {"text": text, "prompt_type": prompt_type, "system_prompt": system_prompt}
            )
            if len(self.calls) <= 2:
                return big
            return "short"

    client = Dummy()
    cache = ResponseCache(str(tmp_path / "cache.json"))
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, force=True)
    result = explaincode._summarize_manual(
        client, cache, text, chunking="auto", source="src"
    )

    assert result == "short"
    assert len(client.calls) > 3
    out = capsys.readouterr().out
    assert "Hierarchical merge pass" in out


def test_cached_chunks_reused(tmp_path: Path) -> None:
    paragraph = "word " * 2000
    text = "\n\n".join([paragraph, paragraph])

    class Dummy:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def summarize(self, text: str, prompt_type: str, system_prompt: str = "") -> str:
            self.calls.append(
                {"text": text, "prompt_type": prompt_type, "system_prompt": system_prompt}
            )
            return f"resp{len(self.calls)}"

    cache_file = tmp_path / "cache.json"
    cache = ResponseCache(str(cache_file))
    client1 = Dummy()
    result1 = explaincode._summarize_manual(
        client1, cache, text, chunking="auto", source="src"
    )
    assert result1 == "resp3"
    assert len(client1.calls) == 3

    client2 = Dummy()
    cache2 = ResponseCache(str(cache_file))
    result2 = explaincode._summarize_manual(
        client2, cache2, text, chunking="auto", source="src"
    )
    assert result2 == "resp3"
    assert len(client2.calls) == 0


def test_chunking_none_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    big_text = "data " * 5000
    (tmp_path / "README.md").write_text(big_text, encoding="utf-8")

    class Dummy:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def summarize(self, text: str, prompt_type: str, system_prompt: str = "") -> str:
            self.calls.append(
                {"text": text, "prompt_type": prompt_type, "system_prompt": system_prompt}
            )
            return "done"

    dummy = Dummy()
    monkeypatch.setattr(explaincode, "LLMClient", lambda: dummy)
    capsys.readouterr()  # clear any initial warnings
    main(["--path", str(tmp_path), "--chunking", "none"])
    captured = capsys.readouterr()

    assert len(dummy.calls) == 1
    call = dummy.calls[0]
    assert call["prompt_type"] == "user_manual"
    assert call["system_prompt"] == explaincode.MERGE_SYSTEM_PROMPT
    assert "Content exceeds token or character limits; chunking disabled." in captured.err
