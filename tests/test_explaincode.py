import importlib
from pathlib import Path

import pytest

from explaincode import main


def _create_fixture(tmp_path: Path) -> None:
    docs = tmp_path / "Docs"
    docs.mkdir()
    (docs / "page.html").write_text("<html><body><h1>Overview</h1></body></html>", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n\nUsage: run it", encoding="utf-8")
    (tmp_path / "sample.json").write_text("{\"input\": \"data\"}", encoding="utf-8")


def test_html_summary_creation(tmp_path: Path) -> None:
    _create_fixture(tmp_path)
    main(["--path", str(tmp_path)])
    assert (tmp_path / "summary.html").exists()


def test_pdf_summary_creation(tmp_path: Path) -> None:
    if importlib.util.find_spec("reportlab") is None:
        pytest.skip("reportlab not installed")
    _create_fixture(tmp_path)
    main(["--path", str(tmp_path), "--output-format", "pdf"])
    assert (tmp_path / "summary.pdf").exists()


def test_graceful_missing_docx(monkeypatch, tmp_path: Path) -> None:
    _create_fixture(tmp_path)
    try:
        from docx import Document
    except Exception:  # pragma: no cover - dependency missing
        Document = None  # type: ignore
    if Document:
        doc = Document()
        doc.add_paragraph("hi")
        doc.save(tmp_path / "guide.docx")
    import explaincode
    monkeypatch.setattr(explaincode, "Document", None)
    main(["--path", str(tmp_path)])
    assert (tmp_path / "summary.html").exists()
