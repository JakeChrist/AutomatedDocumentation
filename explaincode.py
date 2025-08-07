"""Generate a project summary from existing documentation and sample files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable

from bs4 import BeautifulSoup

try:  # optional dependency
    import markdown  # type: ignore
except Exception:  # pragma: no cover - optional import
    markdown = None

try:  # optional dependency
    from docx import Document  # type: ignore
except Exception:  # pragma: no cover - optional import
    Document = None

try:  # optional dependency
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
except Exception:  # pragma: no cover - optional import
    canvas = None
    letter = None


def collect_files(base: Path) -> Iterable[Path]:
    """Return files from *base* relevant for summarisation."""
    files = []
    docs_dir = base / "Docs"
    if docs_dir.is_dir():
        files.extend(docs_dir.glob("*.html"))

    root_patterns = ["README.md", "*.md", "*.txt", "*.docx", "*.html"]
    for pattern in root_patterns:
        files.extend(base.glob(pattern))

    sample_patterns = ["*.json", "*.csv", "*.txt"]
    for pattern in sample_patterns:
        files.extend(base.glob(pattern))

    seen = set()
    unique = []
    for f in files:
        if f.is_file() and f not in seen:
            unique.append(f)
            seen.add(f)
    return unique


def extract_text(path: Path) -> str:
    """Extract plain text from ``path`` based on its file type."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".html":
            content = path.read_text(encoding="utf-8")
            soup = BeautifulSoup(content, "html.parser")
            return soup.get_text("\n")
        if suffix in {".md"}:
            content = path.read_text(encoding="utf-8")
            if markdown is not None:
                html = markdown.markdown(content)
                soup = BeautifulSoup(html, "html.parser")
                return soup.get_text("\n")
            return content
        if suffix == ".docx" and Document is not None:
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def infer_sections(text: str) -> Dict[str, str]:
    """Naively infer documentation sections from ``text``."""
    sections = {
        "Overview": "",
        "How to Use It": "",
        "Inputs and Outputs": "",
        "System Requirements": "",
    }
    for line in text.splitlines():
        lower = line.lower()
        if not sections["Overview"] and any(k in lower for k in ["overview", "purpose", "project"]):
            sections["Overview"] = line.strip()
        if not sections["How to Use It"] and any(k in lower for k in ["use", "usage", "run", "execute"]):
            sections["How to Use It"] = line.strip()
        if not sections["Inputs and Outputs"] and any(k in lower for k in ["input", "output"]):
            sections["Inputs and Outputs"] = line.strip()
        if not sections["System Requirements"] and any(k in lower for k in ["requirement", "dependency", "requires"]):
            sections["System Requirements"] = line.strip()

    for key, value in sections.items():
        if not value:
            sections[key] = "No information available."
    return sections


def render_html(sections: Dict[str, str]) -> str:
    """Return HTML for ``sections``."""
    parts = [
        "<html><head><meta charset='utf-8'>",
        "<style>body{font-family:Arial,sans-serif;margin:20px;}h2{color:#2c3e50;}</style>",
        "</head><body>",
    ]
    for title, content in sections.items():
        parts.append(f"<h2>{title}</h2><p>{content}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def write_pdf(html: str, path: Path) -> bool:
    """Write ``html`` to ``path`` as a PDF. Returns ``True`` on success."""
    if canvas is None:  # pragma: no cover - optional branch
        return False
    text = BeautifulSoup(html, "html.parser").get_text().splitlines()
    c = canvas.Canvas(str(path), pagesize=letter)
    textobject = c.beginText(40, 750)
    for line in text:
        textobject.textLine(line)
    c.drawText(textobject)
    c.save()
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise project documentation")
    parser.add_argument("--path", default=".", help="target project directory")
    parser.add_argument(
        "--output-format", choices=["html", "pdf"], default="html",
        help="output format for the summary",
    )
    args = parser.parse_args(argv)

    target = Path(args.path)
    files = collect_files(target)
    texts = [extract_text(f) for f in files]
    combined = "\n".join(t for t in texts if t)

    sections = infer_sections(combined)
    html = render_html(sections)

    if args.output_format == "html":
        (target / "summary.html").write_text(html, encoding="utf-8")
    else:
        success = write_pdf(html, target / "summary.pdf")
        if not success:
            print("PDF generation requires the reportlab package.")
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
