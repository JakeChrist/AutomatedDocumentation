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
import json
import html

from tqdm import tqdm

from bs4 import BeautifulSoup

from llm_client import LLMClient, PROMPT_TEMPLATES, sanitize_summary
from cache import ResponseCache
from chunk_utils import get_tokenizer
from summarize_utils import summarize_chunked
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
            for heading in soup.find_all([f"h{i}" for i in range(1, 7)]):
                level = int(heading.name[1])
                text = heading.get_text(" ", strip=True)
                heading.replace_with(soup.new_string("#" * level + " " + text))
            for pre in soup.find_all("pre"):
                code = pre.get_text()
                fenced = "```\n" + code.strip("\n") + "\n```"
                pre.replace_with(soup.new_string(fenced))
            text = soup.get_text("\n")
            lines = [line.strip() for line in text.splitlines()]
            return "\n".join(line for line in lines if line)
        if suffix in {".md"}:
            return path.read_text(encoding="utf-8")
        if suffix == ".docx" and Document is not None:
            doc = Document(str(path))
            lines = []
            for p in doc.paragraphs:
                text = p.text.strip()
                if not text:
                    continue
                style = getattr(p.style, "name", "")
                if style.startswith("Heading"):
                    try:
                        level = int(style.split()[1])
                        lines.append("#" * level + " " + text)
                    except Exception:
                        lines.append(text)
                else:
                    lines.append(text)
            return "\n".join(lines)
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def detect_placeholders(text: str) -> list[str]:
    """Return section names still marked by placeholder tokens."""
    tokens = find_placeholders(text)
    return [name for name, token in SECTION_PLACEHOLDERS.items() if token in tokens]


SECTION_KEYWORDS = {
    "Overview": ["overview"],
    "Purpose & Problem Solving": ["purpose", "problem", "objective", "goal"],
    "How to Run": ["how to run", "usage", "running", "execution", "run"],
    "Inputs": ["input", "inputs"],
    "Outputs": ["output", "outputs"],
    "System Requirements": ["system requirements", "requirements", "dependencies"],
    "Examples": ["example", "examples"],
}

# Maximum number of lines to include in a collected snippet. Limiting
# the snippet size helps avoid large generic blocks from dominating the
# evidence collected for a section.
MAX_SNIPPET_LINES = 20


def map_evidence_to_sections(
    docs: dict[Path, str]
) -> tuple[dict[str, list[tuple[Path, str]]], dict[Path, set[str]]]:
    """Map documentation snippets to manual sections.

    Returns a tuple ``(section_map, file_map)`` where ``section_map`` maps
    section names to a list of ``(source_path, snippet)`` tuples and
    ``file_map`` maps each ``source_path`` to the set of sections it
    contributed to. Only the top 10 snippets (by length) are kept per
    section.
    """

    section_map: dict[str, list[tuple[Path, str]]] = {
        name: [] for name in SECTION_KEYWORDS
    }
    file_map: dict[Path, set[str]] = {}

    skip_dirs = {"tests", "examples", "fixtures"}
    for path, text in docs.items():
        parts_lower = {p.lower() for p in path.parts}
        in_excluded_dir = bool(skip_dirs & parts_lower)
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            lowered = line.strip().lower()
            for section, keywords in SECTION_KEYWORDS.items():
                if any(re.search(rf"\b{re.escape(k)}\b", lowered) for k in keywords):
                    max_lines = 0 if in_excluded_dir else MAX_SNIPPET_LINES
                    snippet_lines: list[str] = []
                    j = idx + 1
                    while j < len(lines) and len(snippet_lines) < max_lines:
                        nxt = lines[j]
                        if not nxt.strip():
                            break
                        if nxt.lstrip().startswith("#") or re.match(r"\s*<h[1-6]", nxt):
                            break
                        snippet_lines.append(nxt.strip())
                        j += 1
                    snippet = line.strip()
                    if snippet_lines:
                        snippet += "\n" + " ".join(snippet_lines).strip()
                    if snippet:
                        if section == "Overview" and in_excluded_dir:
                            break
                        section_map[section].append((path, snippet))
                        file_map.setdefault(path, set()).add(section)
                    break

    for section in section_map:
        entries = section_map[section]
        if section == "Overview":
            def _key(item: tuple[Path, str]) -> tuple[int, int]:
                p, snip = item
                parts_lower = [part.lower() for part in p.parts]
                in_docs = "docs" in parts_lower
                is_readme = p.name.lower() == "readme.md"
                priority = 0 if is_readme or in_docs else 1
                return (priority, -len(snip))

            entries.sort(key=_key)
        else:
            entries.sort(key=lambda x: len(x[1]), reverse=True)
        section_map[section] = entries[:10]

    return section_map, file_map


def rank_code_files(root: Path, patterns: list[str]) -> list[Path]:
    """Return code files under ``root`` ranked by simple heuristics.

    Supports ``.py``, ``.m``, ``.ipynb``, ``.cpp``, ``.h``, and ``.java`` files.
    """

    allowed_exts = {".py", ".m", ".ipynb", ".cpp", ".h", ".java"}
    skip_dirs = {
        "venv",
        ".git",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        "tests",
        "test",
        "examples",
        "example",
        "samples",
        "sample",
        "fixtures",
        "fixture",
    }
    keyword_re = re.compile(
        r"run|main|cli|config|io|dataset|reader|writer|pipeline", re.IGNORECASE
    )
    doc_refs = {p.lower() for p in patterns}

    ranked: list[tuple[int, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d.lower() not in skip_dirs and not d.endswith(".egg-info")
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
    for idx, path in enumerate(
        tqdm(files, desc="Scanning code files", total=len(files))
    ):
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
                "Skipping %s: file size %d exceeds limit %d bytes (elapsed %.2fs)",
                path,
                size,
                max_bytes,
                elapsed,
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

                lines = text.splitlines()

                def _get_segment(node: ast.AST) -> str | None:
                    """Return the source segment for ``node``."""

                    segment = ast.get_source_segment(text, node)
                    if segment is not None:
                        return segment
                    start = getattr(node, "lineno", None)
                    end = getattr(node, "end_lineno", None)
                    if start is None:
                        return None
                    if end is None:
                        end = start
                    # ``lineno`` is 1-indexed
                    return "\n".join(lines[start - 1 : end])

                top_level_assignments: list[str] = []
                top_level_statements: list[str] = []

                for node in tree.body:
                    if isinstance(node, (ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign)):
                        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                            # Skip module docstring (already captured above)
                            if isinstance(node.value.value, str):
                                continue
                        segment = _get_segment(node)
                        if not segment:
                            continue
                        segment = segment.strip()
                        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                            top_level_assignments.append(segment)
                        else:
                            top_level_statements.append(segment)
                    elif isinstance(node, (ast.Import, ast.ImportFrom, ast.If)):
                        segment = _get_segment(node)
                        if not segment:
                            continue
                        segment = segment.strip()
                        if "__name__" in segment and "__main__" in segment:
                            # Handled separately below.
                            continue
                        top_level_statements.append(segment)
                    else:
                        segment = _get_segment(node)
                        if not segment:
                            continue
                        segment = segment.strip()
                        top_level_statements.append(segment)

                if top_level_assignments:
                    formatted = []
                    for snippet in top_level_assignments[:10]:
                        lines_snippet = snippet.splitlines()
                        if len(lines_snippet) > 5:
                            lines_snippet = lines_snippet[:5] + ["..."]
                        formatted.append("\n".join(lines_snippet))
                    parts.append("Top-level variables:\n" + "\n\n".join(formatted))

                if top_level_statements:
                    formatted_statements: list[str] = []
                    for snippet in top_level_statements[:10]:
                        lines_snippet = snippet.splitlines()
                        if len(lines_snippet) > 10:
                            lines_snippet = lines_snippet[:10] + ["..."]
                        formatted_statements.append("\n".join(lines_snippet))
                    parts.append("Top-level code:\n" + "\n\n".join(formatted_statements))

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
) -> dict[str, dict[str, str]]:
    """Collect source code snippets from ``base`` grouped by manual section.

    The function searches source files for keywords associated with
    ``sections`` (defaulting to all known sections) and returns a mapping from
    section name to a mapping of relative file paths and their snippet text.
    """

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

    wanted = sections if sections is not None else list(SECTION_KEYWORDS.keys())
    categorized: dict[str, dict[str, str]] = {sec: {} for sec in wanted}

    for path, text in tqdm(snippets.items(), desc="Collecting snippets"):
        rel = path.relative_to(base)
        lower = text.lower()
        for section in wanted:
            keywords = SECTION_KEYWORDS.get(section, [])
            if any(k in lower for k in keywords):
                categorized.setdefault(section, {})[str(rel)] = text
    return {k: v for k, v in categorized.items() if v}


def llm_generate_manual(
    docs: dict[Path, str],
    client: LLMClient,
    cache: ResponseCache,
    chunking: str = "auto",
) -> tuple[str, dict[Path, set[str]], dict[str, dict[str, object]]]:
    """Generate a manual from supplied documentation ``docs``.

    The function maps documentation snippets to manual sections, performs an
    LLM call per section, and assembles the final manual text. It returns the
    manual text, a mapping of source files to the sections they contributed,
    and an evidence map capturing the snippets used for each section.
    """

    section_map, file_map = map_evidence_to_sections(docs)

    sections: dict[str, str] = {}
    evidence_map: dict[str, dict[str, object]] = {}
    for section in REQUIRED_SECTIONS:
        entries = section_map.get(section, [])
        inferred = not entries
        evidence_map[section] = {
            "inferred": inferred,
            "evidence": [
                {"file": str(path), "snippet": snippet}
                for path, snippet in entries
            ],
        }
        if inferred:
            sections[section] = SECTION_PLACEHOLDERS[section]
            logging.info(
                "Section %s generated with inferred content; evidence: none", section
            )
            continue
        context = "\n\n".join(snippet for _, snippet in entries)
        for path, snippet in entries:
            logging.info("Section %s snippet from %s", section, path)
        prompt = (
            f"Write the '{section}' section of a user manual using the "
            "following documentation snippets."
            f"\n\n{context}"
        )
        placeholder = SECTION_PLACEHOLDERS[section]
        system_prompt = (
            f"You write the '{section}' section of a user manual. "
            "Use only the provided snippets; if they lack relevant facts, "
            f"respond with the placeholder token {placeholder}. Do not infer "
            "information not present in the snippets."
        )
        tokenizer = get_tokenizer()
        template = PROMPT_TEMPLATES["docstring"]
        overhead = len(tokenizer.encode(system_prompt)) + len(
            tokenizer.encode(template.format(text=""))
        )
        max_context_tokens = 4096
        chunk_token_budget = int(max_context_tokens * 0.75)
        available = max_context_tokens - overhead
        if len(tokenizer.encode(prompt)) > available:
            result = summarize_chunked(
                client,
                cache,
                f"section:{section}",
                prompt,
                "docstring",
                system_prompt=system_prompt,
                max_context_tokens=max_context_tokens,
                chunk_token_budget=chunk_token_budget,
            )
        else:
            key = ResponseCache.make_key(f"section:{section}", prompt)
            cached = cache.get(key)
            if cached is not None:
                result = sanitize_summary(cached)
            else:
                result = client.summarize(
                    prompt,
                    "docstring",
                    system_prompt=system_prompt,
                )
                result = sanitize_summary(result)
                cache.set(key, result)
        parsed = parse_manual(result, infer_missing=False)
        text = parsed.get(section, result.strip())
        if placeholder in find_placeholders(text):
            sections[section] = placeholder
        else:
            sections[section] = text
        summary = ", ".join(
            f"{path}: {snippet[:30]}" for path, snippet in entries
        )
        logging.info(
            "Section %s generated using [%s]; inferred=%s",
            section,
            summary or "none",
            inferred,
        )

    manual_text = "\n".join(f"{sec}: {txt}" for sec, txt in sections.items())
    return manual_text, file_map, evidence_map


# Backwards compatibility for older code paths
generate_manual_from_docs = llm_generate_manual


FILL_SYSTEM_PROMPT = (
    "You are enhancing a user manual. Use the provided code snippets to replace placeholder tokens "
    "with the missing information. Do not describe individual functions or implementation details; "
    "focus on user-level instructions."
)


def llm_fill_placeholders(
    manual_text: str,
    code_snippets: dict[str, dict[str, str]],
    client: LLMClient,
    cache: ResponseCache,
    *,
    max_context_tokens: int = 4096,
    chunk_token_budget: int | None = None,
) -> str:
    """Fill placeholder tokens in ``manual_text`` using ``code_snippets``.

    ``code_snippets`` maps section names to dictionaries of ``path -> text``
    containing evidence for that section. A separate LLM call is made for each
    section to update the manual incrementally. Long snippets are summarized
    before being sent to the model so that prompts stay within the model's
    context window.
    """

    tokenizer = get_tokenizer()
    if chunk_token_budget is None:
        chunk_token_budget = int(max_context_tokens * 0.75)

    for section, files in code_snippets.items():
        if not files:
            continue
        snippet_text = "\n\n".join(
            f"# File: {path}\n{text}" for path, text in files.items()
        )

        token_usage = len(tokenizer.encode(manual_text)) + len(
            tokenizer.encode(snippet_text)
        )
        if token_usage > max_context_tokens:
            snippet_text = summarize_chunked(
                client,
                cache,
                f"fill_manual:{section}:snippet",
                snippet_text,
                "docstring",
                system_prompt=FILL_SYSTEM_PROMPT,
                max_context_tokens=max_context_tokens,
                chunk_token_budget=chunk_token_budget,
            )

        prompt = (
            f"Manual:\n{manual_text}\n\n"
            f"Section: {section}\n"
            f"Code Snippets:\n{snippet_text}\n\n"
            "Update the manual by replacing the placeholder for this section with the relevant information from the code snippets."
        )

        manual_text = summarize_chunked(
            client,
            cache,
            f"fill_manual:{section}",
            prompt,
            "docstring",
            system_prompt=FILL_SYSTEM_PROMPT,
            max_context_tokens=max_context_tokens,
            chunk_token_budget=chunk_token_budget,
        )

        logging.info(
            "Filled %s using code from: %s", section, ", ".join(files.keys())
        )
    return manual_text


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



def render_html(
    sections: Dict[str, str],
    title: str,
    evidence_map: dict[str, dict[str, object]] | None = None,
) -> str:
    """Return HTML for ``sections`` with ``title``.

    ``evidence_map`` contains supporting snippets for each section. When a
    section's content is empty or marked as lacking information, available
    evidence snippets are rendered instead so that the manual always reflects
    the extracted documentation.
    """

    def _slugify(text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
        return slug.strip("-")

    nav_items: list[str] = []
    body_parts: list[str] = []

    for sec_title, content in sections.items():
        anchor = _slugify(sec_title)
        nav_items.append(
            f"<li><a href='#" + anchor + f"'>{html.escape(sec_title)}</a></li>"
        )

        evidence = []
        if evidence_map:
            evidence = evidence_map.get(sec_title, {}).get("evidence", [])
        text = content.strip()
        if (not text or text.lower() == "no information provided.") and evidence:
            snippets = "<br/>".join(
                html.escape(e.get("snippet", "")) for e in evidence if e.get("snippet")
            )
            src_items = [
                f"<li>{html.escape(e.get('file', ''))}</li>"
                for e in evidence
                if e.get("file")
            ]
            sources_block = (
                f"<div class='sources'><ul>{''.join(src_items)}</ul></div>"
                if src_items
                else ""
            )
            body_parts.append(
                f"<h2 id='{anchor}'>{html.escape(sec_title)}</h2><p>{snippets}</p>{sources_block}"
            )
        else:
            if not text:
                text = "No information provided."
            if markdown is not None:
                try:
                    rendered = markdown.markdown(
                        text, extensions=["fenced_code", "tables"]
                    )
                except Exception:
                    rendered = html.escape(text)
            else:  # pragma: no cover - optional dependency missing
                rendered = html.escape(text)
            body_parts.append(
                f"<h2 id='{anchor}'>{html.escape(sec_title)}</h2>{rendered}"
            )

    parts = [
        "<html><head><meta charset='utf-8'>",
        (
            "<style>body{font-family:Arial,sans-serif;margin:20px;}h2{color:#2c3e50;}"
            ".evidence{margin-left:1em;color:#555;font-size:0.9em;}"
            ".sources{margin-left:1em;font-size:0.9em;}"
            ".sources ul{margin:0;padding-left:1.2em;}</style>"
        ),
        "</head><body>",
        f"<h1>{html.escape(title)}</h1>",
        "<nav><ul>",
        "".join(nav_items),
        "</ul></nav>",
        "".join(body_parts),
        "</body></html>",
    ]
    return "\n".join(parts)


def parse_manual(
    text: str,
    client: "LLMClient | None" = None,
    infer_missing: bool = True,
) -> Dict[str, str]:
    """Parse ``text`` from the LLM into structured sections.

    The language model may return any set of headings. This parser splits the
    input on lines containing a colon (``Section: content``) and keeps the
    sections in the order they appear. When ``infer_missing`` is ``True``,
    absent required sections are inferred using the language model and marked
    as ``(inferred)``.
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

    missing = [key for key in REQUIRED_SECTIONS if not sections.get(key, "").strip()]
    if infer_missing and missing:
        if client is None:
            client = LLMClient()
        for key in missing:
            prompt = (
                f"Based on the following manual draft, write a short '{key}' section.\n\n{text}"
            )
            try:
                guess = client.summarize(
                    prompt,
                    "docstring",
                    system_prompt=f"You fill in the '{key}' section of a user manual.",
                )
            except Exception:  # pragma: no cover - network issues
                guess = ""
            sections[key] = (guess.strip() or f"{key} details") + " (inferred)"

    return sections


def validate_manual_references(
    sections: Dict[str, str],
    project_root: Path,
    evidence_map: dict[str, dict[str, object]] | None = None,
) -> None:
    """Flag references in ``sections`` that lack corresponding files.

    Each section's text is scanned for substrings that resemble file paths or
    module names (e.g., ``module.py`` or ``sub/dir/file.m``). If a referenced
    file cannot be found anywhere under ``project_root``, the reference is
    annotated with ``[missing]`` in the section text. When ``evidence_map`` is
    provided, missing references are also recorded under the corresponding
    section in a ``missing_references`` list.

    The ``sections`` mapping is modified in place.
    """

    pattern = re.compile(
        r"\b[\w./-]+\.(?:py|m|md|rst|txt|json|yaml|yml|csv)\b"
    )

    existing_paths = {
        p.relative_to(project_root).as_posix()
        for p in project_root.rglob("*")
        if p.is_file()
    }
    existing_names = {Path(p).name for p in existing_paths}

    for title, text in sections.items():
        missing: list[str] = []

        def repl(match: re.Match[str]) -> str:
            ref = match.group(0)
            if ref in existing_paths or ref in existing_names:
                return ref
            missing.append(ref)
            return f"{ref} [missing]"

        updated = pattern.sub(repl, text)
        sections[title] = updated
        if missing and evidence_map is not None:
            evidence_map.setdefault(title, {}).setdefault(
                "missing_references", []
            ).extend(missing)


def infer_sections(text: str) -> Dict[str, str]:
    """Infer manual sections heuristically from plain ``text``.

    This is a lightweight fallback used when the language model cannot provide
    a structured summary. When ``text`` is non-empty, the combined text is
    placed in the ``Overview`` section and placeholder content labelled
    ``(inferred)`` is generated for the remaining sections. If ``text`` is
    empty, a default message is used to indicate that no information exists.
    """

    sections: Dict[str, str] = {}
    text = text.strip()
    if text:
        sections["Overview"] = text
        for key in REQUIRED_SECTIONS:
            sections.setdefault(key, f"{key} details (inferred)")
    else:
        for key in REQUIRED_SECTIONS:
            sections[key] = "No information provided."
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
    doc_texts = {f: extract_text(f) for f in tqdm(files, desc="Reading docs")}
    texts = list(doc_texts.values())
    logging.basicConfig(
        level=logging.DEBUG if config.chunking != "none" else logging.INFO
    )

    logging.info("DOC PASS started with %d files", len(files))
    logging.info("Files: %s", ", ".join(str(f) for f in files))

    client = LLMClient()
    cache = ResponseCache(str(out_dir / "cache.json"))
    evidence_map: dict[str, dict[str, object]] = {}
    try:
        ping = getattr(client, "ping", None)
        if callable(ping):
            ping()
        response, file_sections, evidence_map = llm_generate_manual(
            doc_texts, client, cache, config.chunking
        )
        for f in files:
            sections = sorted(file_sections.get(f, set()))
            logging.info(
                "%s contributes to sections: %s",
                f,
                ", ".join(sections) if sections else "none",
            )
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
        sections = parse_manual(response, infer_missing=False)
        validate_manual_references(sections, target, evidence_map)
    except Exception as exc:  # pragma: no cover - network or attribute failure
        print(
            f"[INFO] LLM summarization failed; using fallback: {exc}",
            file=sys.stderr,
        )
        combined = "\n".join(t for t in texts if t)
        sections = infer_sections(combined)
        evidence_map = {}
        validate_manual_references(sections, target, evidence_map)
    html = render_html(sections, config.title, evidence_map)

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

    evidence_path = out_file.with_name(f"{out_file.stem}_evidence.json")
    evidence_path.write_text(
        json.dumps(evidence_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
