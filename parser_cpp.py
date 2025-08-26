"""Simple parser for C++ files used by DocGen-LM.

This module employs straightforward line-based parsing to extract
namespaces, classes, functions and public variables. It returns a
structure compatible with :func:`parse_python_file` containing
``module_docstring``, ``classes`` and ``functions``. Each item also
stores its ``source`` snippet and any leading documentation comments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple


def _get_preceding_comment(lines: List[str], idx: int) -> str:
    """Collect contiguous comment lines appearing before ``idx``."""

    comments: List[str] = []
    j = idx - 1
    while j >= 0:
        line = lines[j].strip()
        if line.startswith("//"):
            comments.insert(0, line.lstrip("/ "))
            j -= 1
            continue
        if line.endswith("*/"):
            if "/*" in line:
                comments.insert(0, line.strip().lstrip("/* ").rstrip("*/ "))
                break
            block: List[str] = []
            block.insert(0, line)
            j -= 1
            while j >= 0 and "/*" not in lines[j]:
                block.insert(0, lines[j])
                j -= 1
            if j >= 0:
                block.insert(0, lines[j])
            cleaned = [b.strip().lstrip("/* ").rstrip("*/ ") for b in block]
            comments = cleaned + comments
            break
        if line == "":
            if comments:
                break
            j -= 1
            continue
        break
    return "\n".join(c for c in comments if c).strip()


def _extract_block(lines: List[str], start: int) -> Tuple[str, int]:
    """Return text and ending index for block starting at ``start``."""

    text_lines = [lines[start]]
    brace = lines[start].count("{") - lines[start].count("}")
    i = start + 1
    while i < len(lines) and brace > 0:
        line = lines[i]
        text_lines.append(line)
        brace += line.count("{") - line.count("}")
        i += 1
    return "\n".join(text_lines), i - 1


def _parse_class_body(lines: List[str], start: int, end: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse class body and return lists of public methods and variables."""

    methods: List[Dict[str, Any]] = []
    variables: List[Dict[str, Any]] = []
    access = "private"
    i = start
    while i <= end:
        line = lines[i].strip()
        if line in {"public:", "protected:", "private:"}:
            access = line.rstrip(":")
            i += 1
            continue
        if access == "public":
            if "(" in line and line.rstrip().endswith("{"):
                sig = line.rstrip("{").strip()
                name = sig.split("(")[0].split()[-1]
                doc = _get_preceding_comment(lines, i)
                block, end_idx = _extract_block(lines, i)
                methods.append({"name": name, "signature": sig, "docstring": doc, "source": block})
                i = end_idx + 1
                continue
            if line.endswith(";") and "(" not in line:
                parts = line.rstrip(";").split()
                if parts:
                    name = parts[-1]
                    vartype = " ".join(parts[:-1])
                    doc = _get_preceding_comment(lines, i)
                    variables.append({"name": name, "type": vartype, "docstring": doc, "source": lines[i]})
        i += 1
    return methods, variables


def parse_cpp_file(path: str) -> Dict[str, Any]:
    """Parse a C++ source file and return structured information."""

    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()

    # Module-level comment
    first_code = 0
    while first_code < len(lines):
        stripped = lines[first_code].strip()
        if stripped == "" or stripped.startswith("//") or stripped.startswith("/*"):
            first_code += 1
            continue
        break
    module_docstring = _get_preceding_comment(lines, first_code)

    namespace = None
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if namespace is None and stripped.startswith("namespace "):
            namespace = stripped.split()[1]
            if namespace.endswith("{"):
                namespace = namespace[:-1]
        if stripped.startswith("class ") or stripped.startswith("struct "):
            name = stripped.split()[1]
            if name.endswith("{"):
                name = name[:-1]
            doc = _get_preceding_comment(lines, i)
            block, end_idx = _extract_block(lines, i)
            methods, variables = _parse_class_body(lines, i + 1, end_idx - 1)
            classes.append({"name": name, "docstring": doc, "methods": methods, "variables": variables, "source": block})
            i = end_idx + 1
            continue
        if "(" in stripped and stripped.endswith("{") and not stripped.startswith(("if", "for", "while", "switch")) and "class " not in stripped and "struct " not in stripped:
            sig = stripped.rstrip("{").strip()
            name = sig.split("(")[0].split()[-1]
            doc = _get_preceding_comment(lines, i)
            block, end_idx = _extract_block(lines, i)
            functions.append({"name": name, "signature": sig, "docstring": doc, "source": block})
            i = end_idx + 1
            continue
        i += 1

    result: Dict[str, Any] = {"module_docstring": module_docstring, "classes": classes, "functions": functions}
    if namespace:
        result["namespace"] = namespace
    return result
