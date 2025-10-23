"""Parsers for JavaScript and TypeScript source files used by DocGen-LM."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


_FUNC_DEF_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*(?::\s*[^({]+)?"
)
_ARROW_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*(?::\s*[^=]+)?=>"
)
_ARROW_SIMPLE_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*=>"
)
_FUNC_EXPR_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function\s*\(([^)]*)\)"
)
_CLASS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"
)
_METHOD_RE = re.compile(
    r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:async\s+)?([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*(?::\s*[^({]+)?\s*\{"
)
_PROPERTY_RE = re.compile(
    r"^\s*(?:public|private|protected)?\s*(?:static\s+)?([A-Za-z_$][\w$]*)\s*(?::\s*[^=;{]+)?\s*(?:=[^;{]+)?;"
)


def _clean_comment_lines(lines: List[str]) -> List[str]:
    """Return ``lines`` stripped of JavaScript/TypeScript comment markers."""

    cleaned: List[str] = []
    for raw in lines:
        text = raw.strip()
        if not text:
            cleaned.append("")
            continue
        if text.startswith("//"):
            cleaned.append(text.lstrip("/ ").strip())
            continue
        # Remove block comment markers and leading asterisks as used in JSDoc.
        text = text.lstrip("/* ").rstrip("*/ ").strip()
        if text.startswith("*"):
            text = text.lstrip("* ").strip()
        if text.endswith("*/"):
            text = text.rstrip("*/ ").strip()
        cleaned.append(text)
    return cleaned


def _get_preceding_comment(lines: List[str], idx: int) -> str:
    """Return the block or line comments immediately preceding ``idx``."""

    if idx <= 0:
        return ""

    comments: List[str] = []
    j = idx - 1
    while j >= 0:
        raw = lines[j]
        stripped = raw.strip()
        if stripped.startswith("//"):
            comments.insert(0, raw)
            j -= 1
            continue
        if stripped.endswith("*/"):
            block: List[str] = [raw]
            j -= 1
            while j >= 0:
                candidate = lines[j]
                if "/*" in candidate:
                    block.insert(0, candidate)
                    break
                if candidate.strip() == "":
                    break
                block.insert(0, candidate)
                j -= 1
            comments = block + comments
            break
        if stripped == "":
            if comments:
                break
            j -= 1
            continue
        break

    cleaned = [line for line in _clean_comment_lines(comments) if line]
    return "\n".join(cleaned).strip()


def _extract_block(lines: List[str], start: int) -> Tuple[str, int]:
    """Return the text of a brace-delimited block starting at ``start``."""

    text_lines = [lines[start]]
    depth = lines[start].count("{") - lines[start].count("}")
    i = start + 1
    while i < len(lines) and depth > 0:
        text_lines.append(lines[i])
        depth += lines[i].count("{") - lines[i].count("}")
        i += 1
    end_idx = i - 1 if depth <= 0 else len(lines) - 1
    return "\n".join(text_lines), end_idx


def _parse_class_body(lines: List[str], start: int, end: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    methods: List[Dict[str, Any]] = []
    variables: List[Dict[str, Any]] = []
    i = start
    while i <= end and i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith(("//", "/*", "*")):
            i += 1
            continue

        method_match = _METHOD_RE.match(lines[i])
        if method_match:
            name = method_match.group(1)
            signature = lines[i].strip().split("{")[0].strip()
            doc = _get_preceding_comment(lines, i)
            block, method_end = _extract_block(lines, i)
            methods.append(
                {
                    "name": name,
                    "signature": signature,
                    "docstring": doc,
                    "source": block,
                    "subfunctions": [],
                }
            )
            i = max(i + 1, method_end + 1)
            continue

        prop_match = _PROPERTY_RE.match(lines[i])
        if prop_match:
            name = prop_match.group(1)
            doc = _get_preceding_comment(lines, i)
            variables.append(
                {
                    "name": name,
                    "docstring": doc,
                    "source": lines[i].strip(),
                }
            )
            i += 1
            continue

        i += 1

    return methods, variables


def _module_docstring(lines: List[str]) -> str:
    doc_lines: List[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "":
            if doc_lines:
                break
            i += 1
            continue
        if stripped.startswith("//"):
            doc_lines.append(lines[i])
            i += 1
            continue
        if stripped.startswith("/*"):
            block: List[str] = [lines[i]]
            if "*/" in stripped:
                i += 1
            else:
                i += 1
                while i < len(lines):
                    block.append(lines[i])
                    if "*/" in lines[i]:
                        i += 1
                        break
                    i += 1
            doc_lines.extend(block)
            break
        break

    cleaned = [line for line in _clean_comment_lines(doc_lines) if line]
    return "\n".join(cleaned).strip()


def _parse_js_or_ts(path: str) -> Dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()

    module_docstring = _module_docstring(lines)

    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    variables: List[Dict[str, Any]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith(("//", "/*", "*")):
            i += 1
            continue

        class_match = _CLASS_RE.match(line)
        if class_match:
            name = class_match.group(1)
            doc = _get_preceding_comment(lines, i)
            block, end_idx = _extract_block(lines, i)
            body_start = min(len(lines), i + 1)
            body_end = end_idx - 1
            if body_start >= len(lines) or body_end < body_start:
                methods, class_vars = [], []
            else:
                methods, class_vars = _parse_class_body(lines, body_start, body_end)
            classes.append(
                {
                    "name": name,
                    "docstring": doc,
                    "methods": methods,
                    "variables": class_vars,
                    "subclasses": [],
                    "source": block,
                }
            )
            i = max(i + 1, end_idx + 1)
            continue

        func_match = _FUNC_DEF_RE.match(line)
        if func_match:
            name = func_match.group(1)
            signature = line.strip().split("{")[0].strip()
            doc = _get_preceding_comment(lines, i)
            block, end_idx = _extract_block(lines, i) if "{" in line else (line.strip(), i)
            functions.append(
                {
                    "name": name,
                    "signature": signature,
                    "docstring": doc,
                    "source": block,
                    "subfunctions": [],
                    "calls": [],
                }
            )
            i = max(i + 1, end_idx + 1)
            continue

        arrow_match = _ARROW_FUNC_RE.match(line) or _FUNC_EXPR_RE.match(line)
        if arrow_match:
            name = arrow_match.group(1)
            params = arrow_match.group(2).strip()
            signature_params = params
            doc = _get_preceding_comment(lines, i)
            signature = f"{name}({signature_params})"
            if not signature_params:
                signature = f"{name}()"
            block, end_idx = _extract_block(lines, i) if "{" in line else (line.strip(), i)
            functions.append(
                {
                    "name": name,
                    "signature": signature,
                    "docstring": doc,
                    "source": block,
                    "subfunctions": [],
                    "calls": [],
                }
            )
            i = max(i + 1, end_idx + 1)
            continue

        simple_arrow = _ARROW_SIMPLE_RE.match(line)
        if simple_arrow:
            name = simple_arrow.group(1)
            param = simple_arrow.group(2)
            doc = _get_preceding_comment(lines, i)
            signature = f"{name}({param})"
            block = line.strip()
            functions.append(
                {
                    "name": name,
                    "signature": signature,
                    "docstring": doc,
                    "source": block,
                    "subfunctions": [],
                    "calls": [],
                }
            )
            i += 1
            continue

        top_var = _PROPERTY_RE.match(line)
        if top_var:
            name = top_var.group(1)
            doc = _get_preceding_comment(lines, i)
            variables.append(
                {
                    "name": name,
                    "docstring": doc,
                    "source": line.strip(),
                }
            )
            i += 1
            continue

        i += 1

    return {
        "module_docstring": module_docstring,
        "functions": functions,
        "classes": classes,
        "variables": variables,
    }


def parse_javascript_file(path: str) -> Dict[str, Any]:
    """Parse a JavaScript source file and return structured metadata."""

    return _parse_js_or_ts(path)


def parse_typescript_file(path: str) -> Dict[str, Any]:
    """Parse a TypeScript source file and return structured metadata."""

    return _parse_js_or_ts(path)
