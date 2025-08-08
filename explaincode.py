"""Generate a project summary from existing documentation and sample files."""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, Iterable
import sys

from bs4 import BeautifulSoup

from llm_client import LLMClient
from chunk_utils import get_tokenizer, chunk_text
from cache import ResponseCache

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

    missing: list[str] = []
    for name, token in SECTION_PLACEHOLDERS.items():
        if token in text:
            missing.append(name)
    return missing


def scan_code(base: Path, sections: list[str] | None = None) -> str:
    """Collect source code snippets from ``base``.

    ``sections`` can specify which manual sections are missing; it is currently
    unused but retained for compatibility with future implementations.
    """

    try:
        from scanner import scan_directory
    except Exception:  # pragma: no cover - defensive
        return ""

    try:
        files = scan_directory(str(base), [])
    except Exception:  # pragma: no cover - defensive
        files = []

    snippets: list[str] = []
    for filename in files:
        path = Path(filename)
        try:
            snippets.append(path.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover - best effort
            continue
    return "\n\n".join(snippets)


def generate_manual_from_docs(
    docs: list[str],
    client: LLMClient,
    cache: ResponseCache,
    chunking: str = "auto",
) -> str:
    """Generate a manual from supplied documentation ``docs``."""

    text = "\n".join(d for d in docs if d)
    return _summarize_manual(client, cache, text, chunking=chunking, source="docs")


TOKENIZER = get_tokenizer()
CHUNK_SYSTEM_PROMPT = (
    "You are generating part of a user manual. Based on the context provided, "
    "write a section of the guide covering purpose, usage, inputs, outputs, and behavior."
)
MERGE_SYSTEM_PROMPT = (
    "You are compiling a user manual. Combine the provided sections into a cohesive guide. "
    "Ensure the manual includes sections for Overview, Purpose & Problem Solving, How to Run, "
    "Inputs, Outputs, System Requirements, and Examples. If information for any section is "
    "missing, insert the corresponding placeholder token such as [[NEEDS_RUN_INSTRUCTIONS]]."
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
    cache: ResponseCache,
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
        partials: dict[int, str] = {}
        work: list[tuple[int, str, str]] = []
        for idx, part in enumerate(parts, 1):
            logging.debug(
                "Chunk %s/%s from %s: %s tokens, %s characters",
                idx,
                total,
                source,
                _count_tokens(part),
                len(part),
            )
            key = ResponseCache.make_key(f"{source}:chunk{idx}", part)
            cached = cache.get(key)
            if cached is not None:
                partials[idx] = cached
                logging.debug(
                    "LLM response %s/%s length: %s characters",
                    idx,
                    total,
                    len(cached),
                )
            else:
                work.append((idx, part, key))

        if work:
            with ThreadPoolExecutor() as executor:
                future_map = {
                    executor.submit(
                        client.summarize,
                        part,
                        "docstring",
                        system_prompt=CHUNK_SYSTEM_PROMPT,
                    ): (idx, key)
                    for idx, part, key in work
                }
                for future in as_completed(future_map):
                    idx, key = future_map[future]
                    try:
                        resp = future.result()
                    except Exception as exc:  # pragma: no cover - network failure
                        print(
                            f"[WARN] Summarization failed for chunk {idx}/{total}: {exc}",
                            file=sys.stderr,
                        )
                        continue
                    cache.set(key, resp)
                    logging.debug(
                        "LLM response %s/%s length: %s characters",
                        idx,
                        total,
                        len(resp),
                    )
                    partials[idx] = resp

        if not partials:
            sections = infer_sections(text)
            return "\n".join(f"{k}: {v}" for k, v in sections.items())

        if post_chunk_hook:
            try:
                ordered = [partials[i] for i in sorted(partials)]
                ordered = post_chunk_hook(ordered)
                partials = {i + 1: v for i, v in enumerate(ordered)}
            except Exception as exc:  # pragma: no cover - defensive
                logging.debug("Chunk post-processing failed: %s", exc)

        merge_input = "\n\n".join(partials[i] for i in sorted(partials))
        tokens = _count_tokens(merge_input)
        chars = len(merge_input)
        iteration = 0
        while tokens > 2000 or chars > 6000:
            iteration += 1
            logging.info(
                "Hierarchical merge pass %s: %s tokens, %s characters",
                iteration,
                tokens,
                chars,
            )
            try:
                sub_parts = _split_text(merge_input)
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[WARN] Hierarchical split failed: {exc}", file=sys.stderr)
                break
            new_partials: list[str] = []
            total = len(sub_parts)
            for idx, piece in enumerate(sub_parts, 1):
                logging.debug(
                    "Merge chunk %s/%s: %s tokens, %s characters",
                    idx,
                    total,
                    _count_tokens(piece),
                    len(piece),
                )
                key = ResponseCache.make_key(
                    f"{source}:merge{iteration}:chunk{idx}", piece
                )
                cached = cache.get(key)
                if cached is not None:
                    resp = cached
                else:
                    try:
                        resp = client.summarize(
                            piece, "docstring", system_prompt=MERGE_SYSTEM_PROMPT
                        )
                    except Exception as exc:  # pragma: no cover - network failure
                        print(
                            f"[WARN] Hierarchical summarization failed for chunk {idx}/{total}: {exc}",
                            file=sys.stderr,
                        )
                        continue
                    cache.set(key, resp)
                new_partials.append(resp)
            if not new_partials:
                break
            merge_input = "\n\n".join(new_partials)
            tokens = _count_tokens(merge_input)
            chars = len(merge_input)
        key = ResponseCache.make_key(f"{source}:final", merge_input)
        cached = cache.get(key)
        if cached is not None:
            final_resp = cached
        else:
            try:
                final_resp = client.summarize(
                    merge_input, "docstring", system_prompt=MERGE_SYSTEM_PROMPT
                )
                cache.set(key, final_resp)
            except Exception as exc:  # pragma: no cover - network failure
                print(f"[WARN] Merge failed: {exc}", file=sys.stderr)
                return merge_input
        logging.debug("Merged LLM response length: %s characters", len(final_resp))
        return final_resp

    if chunking == "none" and not within_limits:
        print(
            "[WARN] Content exceeds token or character limits; chunking disabled.",
            file=sys.stderr,
        )
    key = ResponseCache.make_key(f"{source}:full", text)
    cached = cache.get(key)
    if cached is not None:
        return cached
    resp = client.summarize(text, "user_manual", system_prompt=MERGE_SYSTEM_PROMPT)
    cache.set(key, resp)
    return resp



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
    args = parser.parse_args(argv)

    target = Path(args.path)
    out_dir = Path(args.output) if args.output else target
    out_dir.mkdir(parents=True, exist_ok=True)
    files = collect_docs(target)
    texts = [extract_text(f) for f in files]
    logging.basicConfig(level=logging.DEBUG if args.chunking != "none" else logging.INFO)

    client = LLMClient()
    cache = ResponseCache(str(out_dir / "cache.json"))
    try:
        ping = getattr(client, "ping", None)
        if callable(ping):
            ping()
        response = generate_manual_from_docs(texts, client, cache, args.chunking)
        missing = detect_placeholders(response)
        if missing and args.scan_code_if_needed:
            code_context = scan_code(target, missing)
            if code_context:
                response = generate_manual_from_docs(
                    texts + [code_context], client, cache, args.chunking
                )
                missing = detect_placeholders(response)
        sections = parse_manual(response)
    except Exception as exc:  # pragma: no cover - network or attribute failure
        print(
            f"[INFO] LLM summarization failed; using fallback: {exc}",
            file=sys.stderr,
        )
        combined = "\n".join(t for t in texts if t)
        sections = infer_sections(combined)
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
