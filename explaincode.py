"""Generate a project summary from existing documentation and sample files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, Iterable

from bs4 import BeautifulSoup

from llm_client import LLMClient

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


def collect_files(base: Path, extra_patterns: Iterable[str] | None = None) -> Iterable[Path]:
    """Return files from *base* relevant for summarisation."""
    files = []
    docs_dir = base / "Docs"
    if docs_dir.is_dir():
        files.extend(docs_dir.glob("*.html"))

    root_patterns = ["README.md", "*.txt", "*.html", "*.docx"]
    for pattern in root_patterns:
        files.extend(base.glob(pattern))

    sample_patterns = ["*.csv", "*.json", "*.txt"]
    for pattern in sample_patterns:
        files.extend(base.glob(pattern))

    if extra_patterns:
        for pattern in extra_patterns:
            files.extend(base.glob(pattern))

    seen = set()
    unique = []
    for f in files:
        if f.is_file() and f not in seen:
            unique.append(f)
            seen.add(f)
    return unique


def slugify(text: str) -> str:
    """Return filesystem-friendly slug from ``text``."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower())
    return slug.strip("_") or "user_manual"


def insert_into_index(index_path: Path, title: str, filename: str) -> None:
    """Append a navigation entry linking to ``filename`` into ``index_path``."""
    try:
        soup = BeautifulSoup(index_path.read_text(encoding="utf-8"), "html.parser")
    except Exception:
        return

    container = soup.find("ul") or soup.find("nav")
    if container is None:
        return

    if container.find("a", href=filename):
        return

    a = soup.new_tag("a", href=filename)
    a.string = title

    if container.name == "ul":
        li = soup.new_tag("li")
        li.append(a)
        container.append(li)
    else:  # append directly to a nav element
        container.append(a)

    index_path.write_text(str(soup), encoding="utf-8")


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




def render_html(sections: Dict[str, str], title: str) -> str:
    """Return HTML for ``sections`` with ``title``."""
    parts = [
        "<html><head><meta charset='utf-8'>",
        "<style>body{font-family:Arial,sans-serif;margin:20px;}h2{color:#2c3e50;}</style>",
        "</head><body>",
        f"<h1>{title}</h1>",
    ]
    for sec_title, content in sections.items():
        parts.append(f"<h2>{sec_title}</h2><p>{content}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def parse_manual(text: str) -> Dict[str, str]:
    """Parse ``text`` from the LLM into structured sections."""
    keys = [
        "Overview",
        "Purpose & Problem Solving",
        "How to Run",
        "Inputs",
        "Outputs",
        "System Requirements",
        "Examples",
    ]
    sections: Dict[str, str] = {k: "" for k in keys}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        for key in keys:
            if stripped.lower().startswith(key.lower()):
                current = key
                value = stripped[len(key):].lstrip(": ")
                sections[current] = value
                break
        else:
            if current:
                sections[current] += ("\n" if sections[current] else "") + stripped
    for key in keys:
        sections[key] = sections[key].strip() or "No information provided."
    return sections


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
    parser.add_argument("--output", help="Destination directory for generated summary")
    parser.add_argument("--title", default="User Manual", help="Title for the generated manual")
    parser.add_argument(
        "--include-files",
        action="append",
        default=[],
        help="Additional glob patterns to include. Can be supplied multiple times",
    )
    parser.add_argument(
        "--insert-into-index",
        action="store_true",
        help="Insert link to the manual into docs/index.html",
    )
    args = parser.parse_args(argv)

    target = Path(args.path)
    out_dir = Path(args.output) if args.output else target
    out_dir.mkdir(parents=True, exist_ok=True)
    files = collect_files(target, args.include_files)
    texts = [extract_text(f) for f in files]
    combined = "\n".join(t for t in texts if t)

    client = LLMClient()
    response = client.summarize(combined, "user_manual") if combined else ""
    sections = parse_manual(response)
    html = render_html(sections, args.title)

    base_name = slugify(args.title)
    out_file = out_dir / f"{base_name}.{'html' if args.output_format == 'html' else 'pdf'}"
    if args.output_format == "html":
        out_file.write_text(html, encoding="utf-8")
    else:
        success = write_pdf(html, out_file)
        if not success:
            print("PDF generation requires the reportlab package.")
            return 1

    if args.insert_into_index:
        index_file = out_dir / "index.html"
        if index_file.exists():
            insert_into_index(index_file, args.title, out_file.name)

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
