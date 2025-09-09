"""Sanitize existing HTML documentation using sanitize_summary."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from llm_client import sanitize_summary


def _sanitize_html(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        inner = re.sub(r"<[^>]+>", "", match.group(1))
        cleaned = sanitize_summary(inner)
        return f"<p>{cleaned}</p>"

    return re.sub(r"<p>(.*?)</p>", repl, html, flags=re.DOTALL | re.IGNORECASE)


def sanitize_directory(directory: Path) -> None:
    for path in directory.rglob("*.html"):
        html = path.read_text(encoding="utf-8")
        sanitized = _sanitize_html(html)
        path.write_text(sanitized, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sanitize generated HTML documentation",
    )
    parser.add_argument("directory", help="Path to the HTML output directory")
    args = parser.parse_args(argv)
    sanitize_directory(Path(args.directory))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
