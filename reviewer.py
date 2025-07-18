"""Post-generation documentation reviewer for DocGen-LM HTML output."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable, List

from bs4 import BeautifulSoup

from llm_client import sanitize_summary


ASSISTANT_PHRASES = [
    "you can",
    "note that",
    "this summary",
    "here's how",
    "to run",
    "we can",
    "let's",
    "should you",
    "if you want",
]

HALLUCINATION_TERMS = [
    "tic-tac-toe",
    "checkers",
    "pizza",
    "weather",
    "recipe",
]


def _is_generated_html(text: str) -> bool:
    """Return True if *text* looks like DocGen-LM output."""
    if "<h1>Project Documentation</h1>" in text:
        return True
    if re.search(r"<h2[^>]*>Class:", text):
        return True
    if re.search(r"<h3[^>]*>Method:", text):
        return True
    return False


def _find_line_number(html: str, phrase: str) -> int:
    for i, line in enumerate(html.splitlines(), 1):
        if phrase.lower() in line.lower():
            return i
    return -1


def check_assistant_phrasing(soup: BeautifulSoup, html: str) -> List[str]:
    """Return list of assistant-like phrases found."""
    findings: List[str] = []
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        lower = text.lower()
        for phrase in ASSISTANT_PHRASES:
            if phrase in lower:
                line_no = _find_line_number(html, text)
                findings.append(f'"{text}" (line {line_no})')
                break
    return findings


def check_contradictions(soup: BeautifulSoup) -> List[str]:
    """Return list of contradiction descriptions."""
    findings: List[str] = []
    summary_text = " ".join(p.get_text(" ", strip=True).lower() for p in soup.find_all("p")[:2])
    methods = soup.find_all(
        "h3", string=lambda s: isinstance(s, str) and s.strip().startswith("Method:")
    )
    functions = [
        h
        for h in soup.find_all("h3")
        if not (isinstance(h.string, str) and h.string.strip().startswith("Method:"))
    ]
    classes = soup.find_all(
        "h2", string=lambda s: isinstance(s, str) and s.strip().startswith("Class:")
    )
    if "no methods" in summary_text and methods:
        findings.append(f"'no methods' stated but found {len(methods)} method headers")
    if "no functions" in summary_text and functions:
        findings.append(f"'no functions' stated but found {len(functions)} function headers")
    if "no classes" in summary_text and classes:
        findings.append(f"'no classes' stated but found {len(classes)} class headers")
    return findings


def check_hallucinations(soup: BeautifulSoup) -> List[str]:
    """Return list of hallucination phrases detected."""
    findings: List[str] = []
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True).lower()
        for term in HALLUCINATION_TERMS:
            if term in text:
                findings.append(term)
    return findings


def _sanitize_paragraphs(soup: BeautifulSoup) -> None:
    for p in soup.find_all("p"):
        cleaned = sanitize_summary(p.get_text())
        p.string = cleaned


def _review_file(path: Path, autofix: bool = False) -> List[str]:
    html = path.read_text(encoding="utf-8")
    if not _is_generated_html(html):
        return []
    soup = BeautifulSoup(html, "html.parser")
    results: List[str] = []
    for snippet in check_assistant_phrasing(soup, html):
        results.append(f"[ASSISTANT] {path.name}: {snippet}")
    for desc in check_contradictions(soup):
        results.append(f"[CONTRADICTION] {path.name}: {desc}")
    for term in check_hallucinations(soup):
        results.append(f"[HALLUCINATION] {path.name}: '{term}' mentioned")
    if autofix and results:
        _sanitize_paragraphs(soup)
        path.write_text(str(soup), encoding="utf-8")
    return results


def review_directory(directory: Path, autofix: bool = False) -> None:
    for file in directory.rglob("*.html"):
        try:
            results = _review_file(file, autofix=autofix)
        except Exception as exc:  # pragma: no cover - unexpected parse failure
            print(f"Error reading {file}: {exc}")
            continue
        for line in results:
            print(line)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review generated HTML documentation")
    parser.add_argument("directory", help="Path to the HTML output directory")
    parser.add_argument("--autofix", action="store_true", help="Rewrite files to fix issues")
    args = parser.parse_args(list(argv) if argv is not None else None)

    review_directory(Path(args.directory), autofix=args.autofix)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())

