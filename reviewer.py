"""Post-generation documentation reviewer for DocGen-LM HTML output."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable, List

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
    if "Generated by DocGen-LM" in text:
        return True
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


def _extract_tags(html: str, tag: str) -> List[str]:
    pattern = rf"<{tag}[^>]*>(.*?)</{tag}>"
    return re.findall(pattern, html, flags=re.DOTALL | re.IGNORECASE)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def check_assistant_phrasing(html: str) -> List[str]:
    """Return list of assistant-like phrases found."""
    findings: List[str] = []
    for raw in _extract_tags(html, "p"):
        text = _strip_html(raw).strip()
        lower = text.lower()
        for phrase in ASSISTANT_PHRASES:
            if phrase in lower:
                line_no = _find_line_number(html, text)
                findings.append(f'"{text}" (line {line_no})')
                break
    return findings


def check_contradictions(html: str) -> List[str]:
    """Return list of contradiction descriptions."""
    findings: List[str] = []
    paragraphs = [_strip_html(p).lower() for p in _extract_tags(html, "p")]
    summary_text = " ".join(paragraphs[:2])
    methods = [h for h in _extract_tags(html, "h3") if h.strip().startswith("Method:")]
    functions = [h for h in _extract_tags(html, "h3") if not h.strip().startswith("Method:")]
    classes = [h for h in _extract_tags(html, "h2") if h.strip().startswith("Class:")]
    if "no methods" in summary_text and methods:
        findings.append(f"'no methods' stated but found {len(methods)} method headers")
    if "no functions" in summary_text and functions:
        findings.append(f"'no functions' stated but found {len(functions)} function headers")
    if "no classes" in summary_text and classes:
        findings.append(f"'no classes' stated but found {len(classes)} class headers")
    return findings


def check_hallucinations(html: str) -> List[str]:
    """Return list of hallucination phrases detected."""
    findings: List[str] = []
    for raw in _extract_tags(html, "p"):
        text = _strip_html(raw).lower()
        for term in HALLUCINATION_TERMS:
            if term in text:
                findings.append(term)
    return findings


def _sanitize_paragraphs(html: str) -> str:
    def repl(match):
        cleaned = sanitize_summary(_strip_html(match.group(1)))
        return f"<p>{cleaned}</p>"

    return re.sub(r"<p>(.*?)</p>", repl, html, flags=re.DOTALL | re.IGNORECASE)


def _review_file(path: Path, autofix: bool = False) -> List[str]:
    html = path.read_text(encoding="utf-8")
    if not _is_generated_html(html):
        return []
    results: List[str] = []
    for snippet in check_assistant_phrasing(html):
        results.append(f"[ASSISTANT] {path.name}: {snippet}")
    for desc in check_contradictions(html):
        results.append(f"[CONTRADICTION] {path.name}: {desc}")
    for term in check_hallucinations(html):
        results.append(f"[HALLUCINATION] {path.name}: '{term}' mentioned")
    if autofix and results:
        html = _sanitize_paragraphs(html)
        path.write_text(html, encoding="utf-8")
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

