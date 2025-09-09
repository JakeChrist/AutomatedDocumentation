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
