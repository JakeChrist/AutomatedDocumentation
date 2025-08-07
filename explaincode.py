"""Generate a project summary from existing documentation and sample files."""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, Iterable
import sys

from bs4 import BeautifulSoup

from llm_client import LLMClient
from docgenerator import _get_tokenizer, chunk_text

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



TOKENIZER = _get_tokenizer()
CHUNK_SYSTEM_PROMPT = (
    "You are generating part of a user manual. Based on the context provided, "
    "write a section of the guide covering purpose, usage, inputs, outputs, and behavior."
)
MERGE_SYSTEM_PROMPT = (
    "You are compiling a user manual. Combine the provided sections into a cohesive guide."
)


def _count_tokens(text: str) -> int:
    """Return the approximate token count for ``text``."""

    return len(TOKENIZER.encode(text))


def _split_text(text: str, max_tokens: int = 2000, max_chars: int = 6000) -> list[str]:
    """Split ``text`` into chunks respecting ``max_tokens`` and ``max_chars``.

    Splitting occurs on paragraph boundaries (double newlines). If a single
    paragraph exceeds the limits, it is further split using ``chunk_text``.
    """

    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    token_count = 0
    char_count = 0
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        ptokens = _count_tokens(para)
        pchars = len(para)
        if ptokens > max_tokens or pchars > max_chars:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                token_count = 0
                char_count = 0
            for piece in chunk_text(para, TOKENIZER, max_tokens):
                chunks.append(piece.strip())
            continue
        if (
            token_count + ptokens > max_tokens
            or char_count + pchars > max_chars
        ):
            if current:
                chunks.append("\n\n".join(current).strip())
            current = [para]
            token_count = ptokens
            char_count = pchars
        else:
            current.append(para)
            token_count += ptokens
            char_count += pchars
    if current:
        chunks.append("\n\n".join(current).strip())
    return chunks


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


def _summarize_manual(
    client: LLMClient,
    text: str,
    chunking: str = "auto",
    source: str = "combined",
    post_chunk_hook: Callable[[list[str]], list[str]] | None = None,
) -> str:
    """Return a manual summary for ``text`` using ``chunking`` strategy."""

    if not text:
        return ""
    within_limits = _count_tokens(text) <= 2000 and len(text) <= 6000

    if chunking == "manual" or (chunking == "auto" and not within_limits):
        try:
            parts = _split_text(text)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[WARN] Chunking failed: {exc}", file=sys.stderr)
            sections = infer_sections(text)
            return "\n".join(f"{k}: {v}" for k, v in sections.items())

        total = len(parts)
        partials: list[str] = []
        for idx, part in enumerate(parts, 1):
            logging.debug(
                "Chunk %s/%s from %s: %s tokens, %s characters",
                idx,
                total,
                source,
                _count_tokens(part),
                len(part),
            )
            try:
                resp = client.summarize(part, "docstring", system_prompt=CHUNK_SYSTEM_PROMPT)
            except Exception as exc:  # pragma: no cover - network failure
                print(
                    f"[WARN] Summarization failed for chunk {idx}/{total}: {exc}",
                    file=sys.stderr,
                )
                continue
            logging.debug(
                "LLM response %s/%s length: %s characters",
                idx,
                total,
                len(resp),
            )
            partials.append(resp)

        if not partials:
            sections = infer_sections(text)
            return "\n".join(f"{k}: {v}" for k, v in sections.items())

        if post_chunk_hook:
            try:
                partials = post_chunk_hook(partials)
            except Exception as exc:  # pragma: no cover - defensive
                logging.debug("Chunk post-processing failed: %s", exc)

        merge_input = "\n\n".join(partials)
        try:
            final_resp = client.summarize(
                merge_input, "docstring", system_prompt=MERGE_SYSTEM_PROMPT
            )
            logging.debug("Merged LLM response length: %s characters", len(final_resp))
            return final_resp
        except Exception as exc:  # pragma: no cover - network failure
            print(f"[WARN] Merge failed: {exc}", file=sys.stderr)
            return merge_input

    if chunking == "none" and not within_limits:
        print(
            "[WARN] Content exceeds token or character limits; chunking disabled.",
            file=sys.stderr,
        )
    return client.summarize(text, "user_manual", system_prompt=MERGE_SYSTEM_PROMPT)



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
        "--include-files",
        action="append",
        default=[],
        help="Additional glob patterns to include. Can be supplied multiple times",
    )
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
        "--edit-chunks",
        action="store_true",
        help="Edit chunk summaries in $EDITOR before merging",
    )
    args = parser.parse_args(argv)

    target = Path(args.path)
    out_dir = Path(args.output) if args.output else target
    out_dir.mkdir(parents=True, exist_ok=True)
    files = collect_files(target, args.include_files)
    texts = [extract_text(f) for f in files]
    combined = "\n".join(t for t in texts if t)
    logging.basicConfig(level=logging.DEBUG if args.chunking != "none" else logging.INFO)
    sources = ", ".join(f.name for f in files)

    client = LLMClient()
    try:
        ping = getattr(client, "ping", None)
        if callable(ping):
            ping()
        hook = _edit_chunks_in_editor if args.edit_chunks else None
        response = (
            _summarize_manual(
                client,
                combined,
                args.chunking,
                source=sources or "combined",
                post_chunk_hook=hook,
            )
            if combined
            else ""
        )
    except Exception as exc:  # pragma: no cover - network or attribute failure
        print(
            f"[INFO] LLM summarization failed; using fallback: {exc}",
            file=sys.stderr,
        )
        sections = infer_sections(combined)
    else:
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
