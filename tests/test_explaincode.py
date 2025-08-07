from pathlib import Path
import importlib
import textwrap
import logging
import sys

import pytest

import explaincode
from explaincode import main


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


def test_chunking_triggers_multiple_calls_and_logs(capsys: pytest.CaptureFixture[str]) -> None:
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

    client = Dummy()
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, force=True)
    result = explaincode._summarize_manual(client, text, chunking="auto", source="src")

    assert result == "resp3"
    assert len(client.calls) == 3
    assert [c["system_prompt"] for c in client.calls[:2]] == [
        explaincode.CHUNK_SYSTEM_PROMPT,
        explaincode.CHUNK_SYSTEM_PROMPT,
    ]
    assert client.calls[2]["system_prompt"] == explaincode.MERGE_SYSTEM_PROMPT
    assert client.calls[2]["text"] == "resp1\n\nresp2"

    out = capsys.readouterr().out
    assert "Chunk 1/2 from src" in out
    assert "Merged LLM response length" in out


def test_chunk_edit_hook_applied() -> None:
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

    def hook(chunks: list[str]) -> list[str]:
        return [c.upper() for c in chunks]

    client = Dummy()
    result = explaincode._summarize_manual(
        client, text, chunking="auto", source="src", post_chunk_hook=hook
    )

    assert result == "resp3"
    assert client.calls[2]["text"] == "RESP1\n\nRESP2"


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
