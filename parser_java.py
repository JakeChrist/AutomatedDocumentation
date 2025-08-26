"""Simple parser for Java files used by DocGen-LM.

Extracts package, classes, public methods and variables using naive
line-based parsing. The output mirrors ``parse_python_file`` with keys
``module_docstring``, ``classes`` and ``functions`` (typically empty for
Java). Each entry includes its source code and leading documentation
comments (Javadoc or ``//``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple


def _get_preceding_comment(lines: List[str], idx: int) -> str:
    comments: List[str] = []
    j = idx - 1
    while j >= 0:
        line = lines[j].strip()
        if line.startswith("//"):
            comments.insert(0, line.lstrip("/ "))
            j -= 1
            continue
        if line.endswith("*/"):
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
    methods: List[Dict[str, Any]] = []
    variables: List[Dict[str, Any]] = []
    i = start
    while i <= end:
        line = lines[i].strip()
        if line.startswith("public "):
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
                name = parts[-1]
                vartype = " ".join(parts[1:-1])
                doc = _get_preceding_comment(lines, i)
                variables.append({"name": name, "type": vartype, "docstring": doc, "source": lines[i]})
        i += 1
    return methods, variables


def parse_java_file(path: str) -> Dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()

    first_code = 0
    while first_code < len(lines):
        stripped = lines[first_code].strip()
        if stripped == "" or stripped.startswith("//") or stripped.startswith("/*"):
            first_code += 1
            continue
        break
    module_docstring = _get_preceding_comment(lines, first_code)

    package = None
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if package is None and stripped.startswith("package "):
            package = stripped.split()[1].rstrip(";")
        if "class " in stripped:
            tokens = stripped.split()
            idx = tokens.index("class")
            name = tokens[idx + 1]
            if name.endswith("{"):
                name = name[:-1]
            doc = _get_preceding_comment(lines, i)
            block, end_idx = _extract_block(lines, i)
            methods, variables = _parse_class_body(lines, i + 1, end_idx - 1)
            classes.append({"name": name, "docstring": doc, "methods": methods, "variables": variables, "source": block})
            i = end_idx + 1
            continue
        i += 1

    result: Dict[str, Any] = {"module_docstring": module_docstring, "classes": classes, "functions": functions}
    if package:
        result["package"] = package
    return result
