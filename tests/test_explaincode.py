from pathlib import Path
import importlib
import textwrap

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
