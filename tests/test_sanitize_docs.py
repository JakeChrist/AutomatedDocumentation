"""Tests for sanitize_docs utility."""

from __future__ import annotations

from pathlib import Path

from sanitize_docs import main


def test_sanitize_directory_removes_ai_disclaimer(tmp_path: Path) -> None:
    html_path = tmp_path / "page.html"
    html_path.write_text(
        "<p>As an AI language model, I cannot do that.</p><p>It prints output.</p>",
        encoding="utf-8",
    )
    main([str(tmp_path)])
    result = html_path.read_text(encoding="utf-8")
    assert "As an AI language model" not in result
    assert "<p>It prints output.</p>" in result


def test_sanitize_directory_handles_headings_and_list_items(tmp_path: Path) -> None:
    html_path = tmp_path / "page.html"
    html_path.write_text(
        (
            "<h2>As an AI language model, I cannot do that.\nIt prints output.</h2>"
            "<li>You can run this.\nIt prints output.</li>"
        ),
        encoding="utf-8",
    )
    main([str(tmp_path)])
    result = html_path.read_text(encoding="utf-8")
    assert "As an AI language model" not in result
    assert "You can run this" not in result
    assert "<h2>It prints output.</h2>" in result
    assert "<li>It prints output.</li>" in result
