"""Generate a project summary from existing documentation and sample files."""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable
import sys
import time
import ast

from bs4 import BeautifulSoup

from llm_client import LLMClient
from cache import ResponseCache
from manual_utils import (
    CHUNK_SYSTEM_PROMPT,
    MERGE_SYSTEM_PROMPT,
    _summarize_manual,
    find_placeholders,
)

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


# core manual sections expected in the generated documentation
REQUIRED_SECTIONS = [
    "Overview",
    "Purpose & Problem Solving",
    "How to Run",
    "Inputs",
    "Outputs",
    "System Requirements",
    "Examples",
]


# mapping of required sections to placeholder tokens used when information is
# missing from the documentation sources. This acts as a checklist for coverage.
SECTION_PLACEHOLDERS = {
    "Overview": "[[NEEDS_OVERVIEW]]",
    "Purpose & Problem Solving": "[[NEEDS_PURPOSE]]",
    "How to Run": "[[NEEDS_RUN_INSTRUCTIONS]]",
    "Inputs": "[[NEEDS_INPUTS]]",
    "Outputs": "[[NEEDS_OUTPUTS]]",
    "System Requirements": "[[NEEDS_REQUIREMENTS]]",
    "Examples": "[[NEEDS_EXAMPLES]]",
}


@dataclass
class Config:
    """Configuration parsed from CLI arguments."""

    path: Path
    output_format: str
    output: Path | None
    title: str
    insert_into_index: bool
    chunking: str
    scan_code_if_needed: bool
    no_code: bool
    force_code: bool
    max_code_files: int
    code_time_budget_seconds: int
    max_bytes_per_file: int


def collect_docs(base: Path) -> list[Path]:
    """Return documentation files under ``base``.

    Only the following locations and patterns are included:

    * ``docs/**/*.html`` and ``docs/**/*.md``
    * Project root ``README.md`` and any ``*.md``, ``*.txt``, ``*.html`` or
      ``*.docx`` files
    """

    files: list[Path] = []
    for pattern in ["README.md", "*.md", "*.txt", "*.html", "*.docx"]:
        files.extend(base.glob(pattern))

    docs_dir = base / "docs"
    if docs_dir.exists():
        for pattern in ["**/*.html", "**/*.md"]:
            files.extend(docs_dir.glob(pattern))

    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        if f.is_file() and f not in seen:
            unique.append(f)
            seen.add(f)
    return unique


def collect_files(base: Path, extra_patterns: Iterable[str] | None = None) -> Iterable[Path]:
    """Return files from *base* relevant for summarisation."""
    patterns = [
        "README.md",
        "*.txt",
        "*.html",
        "*.docx",
        "*.csv",
        "*.json",
    ]

    files: list[Path] = []
    for pattern in patterns:
        files.extend(base.rglob(pattern))

    if extra_patterns:
        for pattern in extra_patterns:
            files.extend(base.rglob(pattern))

    seen: set[Path] = set()
    unique: list[Path] = []
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


def inject_user_manual(index_path: Path, title: str, filename: str) -> None:
    """Insert a top-level link to the manual into ``index_path``.

    The link is prepended to the first navigation element (``<nav>`` or ``<ul>``)
    if present. If neither is found, it is inserted at the start of the first
    element in ``<body>`` or the document root.
    """

    try:
        soup = BeautifulSoup(index_path.read_text(encoding="utf-8"), "html.parser")
    except Exception:
        return

    a = soup.new_tag("a", href=filename)
    a.string = title

    nav = soup.find("nav")
    if nav is not None:
        container = nav.find("ul") or nav
    else:
        hero = soup.find(class_=re.compile("hero", re.IGNORECASE))
        container = hero or soup.find("ul") or soup.body or soup

    if container.name == "ul":
        li = soup.new_tag("li")
        li.append(a)
        container.insert(0, li)
    else:
        container.insert(0, a)

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

def detect_placeholders(text: str) -> list[str]:
    """Return section names still marked by placeholder tokens."""
    tokens = find_placeholders(text)
    return [name for name, token in SECTION_PLACEHOLDERS.items() if token in tokens]


def rank_code_files(root: Path, patterns: list[str]) -> list[Path]:
    """Return code files under ``root`` ranked by simple heuristics."""

    allowed_exts = {".py", ".m", ".ipynb"}
    skip_dirs = {"venv", ".git", "__pycache__", "node_modules", "dist", "build"}
    keyword_re = re.compile(
        r"run|main|cli|config|io|dataset|reader|writer|pipeline", re.IGNORECASE
    )
    doc_refs = {p.lower() for p in patterns}

    ranked: list[tuple[int, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in skip_dirs and not d.endswith(".egg-info")
        ]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix not in allowed_exts:
                continue
            rel = str(path.relative_to(root)).lower()
            score = 0
            if keyword_re.search(rel):
                score += 2
            for ptn in doc_refs:
                if ptn and ptn in rel:
                    score += 1
            ranked.append((score, path))

    ranked.sort(key=lambda x: (-x[0], str(x[1])))
    return [p for _, p in ranked]


def extract_snippets(
    files: Iterable[Path],
    *,
    max_files: int,
    time_budget: int,
    max_bytes: int,
) -> dict[Path, str]:
    """Extract relevant code snippets from ``files``."""

    snippets: dict[Path, str] = {}
    start = time.perf_counter()
    for idx, path in enumerate(files):
        elapsed = time.perf_counter() - start
        logging.info("Considering %s (elapsed %.2fs)", path, elapsed)
        if idx >= max_files:
            logging.info("Skipping %s: file limit reached (elapsed %.2fs)", path, elapsed)
            break
        if elapsed > time_budget:
            logging.info(
                "Skipping %s: time budget exceeded (elapsed %.2fs)", path, elapsed
            )
            break
        try:
            size = path.stat().st_size
        except Exception:
            logging.info(
                "Skipping %s: cannot stat file (elapsed %.2fs)", path, elapsed
            )
            continue
        if size > max_bytes:
            logging.info(
                "Skipping %s: exceeds max bytes (elapsed %.2fs)", path, elapsed
            )
            continue
        try:
            text = path.read_text(encoding="utf-8")[:max_bytes]
        except Exception:
            logging.info(
                "Skipping %s: unreadable (elapsed %.2fs)", path, elapsed
            )
            continue

        parts: list[str] = []
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except Exception:
                tree = None
            if tree is not None:
                module_doc = ast.get_docstring(tree)
                if module_doc:
                    parts.append(f"Module docstring:\n{module_doc}")
                for node in ast.walk(tree):
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        doc = ast.get_docstring(node)
                        if doc:
                            kind = "Class" if isinstance(node, ast.ClassDef) else "Function"
                            parts.append(f"{kind} {node.name} docstring:\n{doc}")
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            args = [a.arg for a in node.args.args]
                            if any(
                                re.search(r"(path|file|config|io)", a, re.IGNORECASE)
                                for a in args
                            ):
                                sig = f"def {node.name}({', '.join(args)}):"
                                parts.append(f"I/O signature: {sig}")
                cli_lines = [
                    line.strip()
                    for line in text.splitlines()
                    if "ArgumentParser" in line or "add_argument" in line
                ]
                if cli_lines:
                    parts.append("CLI parser:\n" + "\n".join(cli_lines))
                main_match = re.search(
                    r"if __name__ == ['\"]__main__['\"]:(.*)", text, re.DOTALL
                )
                if main_match:
                    parts.append("__main__ block:\n" + main_match.group(0).strip())
        else:
            parts.append(text)

        if parts:
            snippets[path] = "\n".join(parts)
            logging.info(
                "Scanned %s (elapsed %.2fs)", path, time.perf_counter() - start
            )
    return snippets


def scan_code(
    base: Path,
    sections: list[str] | None = None,
    *,
    max_files: int = 12,
    time_budget: int = 20,
    max_bytes_per_file: int = 200_000,
) -> str:
    """Collect source code snippets from ``base``."""

    patterns: list[str] = []
    for doc in collect_docs(base):
        try:
            text = extract_text(doc)
        except Exception:
            continue
        for match in re.findall(r"[\w/.-]+", text):
            if "/" in match or match.endswith(".py"):
                patterns.append(match)

    files = rank_code_files(base, patterns)
    snippets = extract_snippets(
        files,
        max_files=max_files,
        time_budget=time_budget,
        max_bytes=max_bytes_per_file,
    )

    parts: list[str] = []
    for path, text in snippets.items():
        rel = path.relative_to(base)
        parts.append(f"# File: {rel}\n{text}")
    return "\n\n".join(parts)


def llm_generate_manual(
    docs: list[str],
    client: LLMClient,
    cache: ResponseCache,
    chunking: str = "auto",
) -> str:
    """Generate a manual from supplied documentation ``docs``."""

    text = "\n".join(d for d in docs if d)
    return _summarize_manual(client, cache, text, chunking=chunking, source="docs")


# Backwards compatibility for older code paths
generate_manual_from_docs = llm_generate_manual


FILL_SYSTEM_PROMPT = (
    "You are enhancing a user manual. Use the provided code snippets to replace placeholder tokens "
    "with the missing information. Do not describe individual functions or implementation details; "
    "focus on user-level instructions."
)


def llm_fill_placeholders(
    manual_text: str,
    code_snippets: str,
    client: LLMClient,
    cache: ResponseCache,
) -> str:
    """Fill placeholder tokens in ``manual_text`` using ``code_snippets``."""

    prompt = (
        "Manual:\n"
        + manual_text
        + "\n\nCode Snippets:\n"
        + code_snippets
        + "\n\nUpdate the manual by replacing placeholder tokens with the relevant information from the code snippets."
    )
    key = ResponseCache.make_key("fill_manual", prompt)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = client.summarize(prompt, "docstring", system_prompt=FILL_SYSTEM_PROMPT)
    cache.set(key, result)
    return result


def _edit_chunks_in_editor(chunks: list[str]) -> list[str]:
    """Open ``chunks`` in user's editor for optional modification.

    Chunks are separated by lines containing ``---``. Returns the edited
    chunks after the editor is closed. Empty chunks are discarded.
    """

    separator = "\n\n---\n\n"
    initial = separator.join(chunks)
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as tmp:
        tmp.write(initial)
        tmp.flush()
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        subprocess.call([editor, tmp.name])
        tmp.seek(0)
        data = tmp.read()
    Path(tmp.name).unlink(missing_ok=True)
    parts = re.split(r"\n\s*---\s*\n", data)
    return [p.strip() for p in parts if p.strip()]



def render_html(sections: Dict[str, str], title: str) -> str:
    """Return HTML for ``sections`` with ``title``.

    Sections are rendered dynamically based on the keys returned from the
    language model, allowing arbitrary headings beyond the required set.
    """
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
    """Parse ``text`` from the LLM into structured sections.

    The language model may return any set of headings. This parser splits the
    input on lines containing a colon (``Section: content``) and keeps the
    sections in the order they appear. Missing required sections are appended
    with a default message.
    """

    sections: Dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^([A-Za-z &]+):\s*(.*)$", stripped)
        if match:
            current = match.group(1).strip()
            sections[current] = match.group(2).strip()
        elif current:
            sections[current] += ("\n" if sections[current] else "") + stripped

    for key in REQUIRED_SECTIONS:
        sections[key] = sections.get(key, "").strip() or "No information provided."

    return sections


def infer_sections(text: str) -> Dict[str, str]:
    """Infer manual sections heuristically from plain ``text``.

    This is a lightweight fallback used when the language model cannot
    provide a structured summary. The combined text is placed in the
    ``Overview`` section and other sections receive default messages.
    """

    sections: Dict[str, str] = {}
    text = text.strip()
    if text:
        sections["Overview"] = text
    for key in REQUIRED_SECTIONS:
        sections[key] = sections.get(key, "") or "No information provided."
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
        "--insert-into-index",
        action="store_true",
        help="Insert link to the manual into index.html in the output directory",
    )
    parser.add_argument(
        "--chunking",
        choices=["auto", "manual", "none"],
        default="auto",
        help="Chunking mode: auto (default) chunks only when needed; manual always chunks; none disables chunking.",
    )
    parser.add_argument(
        "--scan-code-if-needed",
        action="store_true",
        help="Scan project code if manual sections are missing after doc pass",
    )
    parser.add_argument("--no-code", action="store_true", help="Do not scan project code")
    parser.add_argument("--force-code", action="store_true", help="Always scan project code")
    parser.add_argument("--max-code-files", type=int, default=12, help="Maximum number of code files to scan")
    parser.add_argument(
        "--code-time-budget-seconds",
        type=int,
        default=20,
        help="Time budget in seconds for scanning code",
    )
    parser.add_argument(
        "--max-bytes-per-file",
        type=int,
        default=200_000,
        help="Maximum bytes to read from each code file",
    )
    args = parser.parse_args(argv)

    config = Config(
        path=Path(args.path),
        output_format=args.output_format,
        output=Path(args.output) if args.output else None,
        title=args.title,
        insert_into_index=args.insert_into_index,
        chunking=args.chunking,
        scan_code_if_needed=args.scan_code_if_needed,
        no_code=args.no_code,
        force_code=args.force_code,
        max_code_files=args.max_code_files,
        code_time_budget_seconds=args.code_time_budget_seconds,
        max_bytes_per_file=args.max_bytes_per_file,
    )

    target = config.path
    docs_index = target / "docs" / "index.html"
    if config.output:
        out_dir = config.output
    else:
        out_dir = docs_index.parent if docs_index.exists() else target
    out_dir.mkdir(parents=True, exist_ok=True)
    files = collect_docs(target)
    texts = [extract_text(f) for f in files]
    logging.basicConfig(
        level=logging.DEBUG if config.chunking != "none" else logging.INFO
    )

    logging.info("DOC PASS started with %d files", len(files))
    logging.info("Files: %s", ", ".join(str(f) for f in files))

    client = LLMClient()
    cache = ResponseCache(str(out_dir / "cache.json"))
    try:
        ping = getattr(client, "ping", None)
        if callable(ping):
            ping()
        response = llm_generate_manual(texts, client, cache, config.chunking)
        missing = detect_placeholders(response)
        if missing:
            logging.info("Pass 1 missing sections: %s", ", ".join(missing))
        else:
            logging.info("Pass 1 complete: no sections missing")

        if config.no_code:
            logging.info("Code scan skipped: --no-code specified")
            should_scan = False
        elif config.force_code:
            logging.info("Code scan triggered: --force-code enabled")
            should_scan = True
        elif config.scan_code_if_needed:
            if missing:
                logging.info(
                    "Code scan triggered: missing sections %s",
                    ", ".join(missing),
                )
                should_scan = True
            else:
                logging.info("Code scan skipped: placeholders resolved")
                should_scan = False
        else:
            logging.info("Code scan skipped: no scan flags provided")
            should_scan = False

        if should_scan:
            code_context = scan_code(
                target,
                missing,
                max_files=config.max_code_files,
                time_budget=config.code_time_budget_seconds,
                max_bytes_per_file=config.max_bytes_per_file,
            )
            if code_context and missing:
                response = llm_fill_placeholders(
                    response, code_context, client, cache
                )
                missing = detect_placeholders(response)
        logging.info(
            "Pass 2 complete. Unresolved placeholders: %s",
            ", ".join(missing) if missing else "none",
        )
        for token in SECTION_PLACEHOLDERS.values():
            response = response.replace(token, "")
        sections = parse_manual(response)
    except Exception as exc:  # pragma: no cover - network or attribute failure
        print(
            f"[INFO] LLM summarization failed; using fallback: {exc}",
            file=sys.stderr,
        )
        combined = "\n".join(t for t in texts if t)
        sections = infer_sections(combined)
    html = render_html(sections, config.title)

    base_name = slugify(config.title)
    out_file = out_dir / f"{base_name}.{'html' if config.output_format == 'html' else 'pdf'}"
    if config.output_format == "html":
        out_file.write_text(html, encoding="utf-8")
    else:
        success = write_pdf(html, out_file)
        if not success:
            print("PDF generation requires the reportlab package.")
            return 1

    if config.insert_into_index:
        if docs_index.exists() and not config.output:
            index_file = docs_index
            inject_user_manual(index_file, config.title, out_file.name)
        else:
            index_file = out_dir / "index.html"
            if index_file.exists():
                if not docs_index.exists() and not config.output:
                    docs_dir = target / "docs"
                    docs_dir.mkdir(parents=True, exist_ok=True)
                    new_path = docs_dir / out_file.name
                    shutil.move(str(out_file), new_path)
                    out_file = new_path
                    rel = os.path.relpath(out_file, index_file.parent)
                else:
                    rel = out_file.name
                inject_user_manual(index_file, config.title, rel)

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
