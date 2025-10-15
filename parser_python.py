"""Parser for Python files used by DocGen-LM.

Uses the `ast` module to extract structures according to the SRS.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional


def _format_arg(arg: ast.arg) -> str:
    """Return ``arg`` formatted with its annotation if present."""
    text = arg.arg
    if arg.annotation is not None:
        text += f": {ast.unparse(arg.annotation)}"
    return text


def _format_arguments(args: ast.arguments) -> str:
    """Return a string representation of ``args``."""

    parts: List[str] = []

    pos_only = args.posonlyargs
    defaults = [None] * (len(pos_only + args.args) - len(args.defaults)) + list(args.defaults)
    default_iter = iter(defaults)

    # positional only
    for arg in pos_only:
        text = _format_arg(arg)
        default = next(default_iter)
        if default is not None:
            text += f"={ast.unparse(default)}"
        parts.append(text)
    if pos_only:
        parts[-1] += "/"

    # regular arguments
    for arg in args.args:
        text = _format_arg(arg)
        default = next(default_iter)
        if default is not None:
            text += f"={ast.unparse(default)}"
        parts.append(text)

    # var positional
    if args.vararg:
        parts.append("*" + _format_arg(args.vararg))
    elif args.kwonlyargs:
        parts.append("*")

    # keyword only
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        text = _format_arg(arg)
        if default is not None:
            text += f"={ast.unparse(default)}"
        parts.append(text)

    # var keyword
    if args.kwarg:
        parts.append("**" + _format_arg(args.kwarg))

    return ", ".join(parts)


def _format_signature(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return a string signature for ``func``."""

    params = _format_arguments(func.args)
    result = f"{func.name}({params})"
    if func.returns is not None:
        result += f" -> {ast.unparse(func.returns)}"
    return result


def _parse_classes(
    nodes: List[ast.AST],
    source: str,
    parent_qualname: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recursively parse all ``ClassDef`` nodes within ``nodes``."""

    classes: List[Dict[str, Any]] = []
    for item in nodes:
        if isinstance(item, ast.ClassDef):
            classes.append(parse_class(item, source, parent_qualname))
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_parent = (
                f"{parent_qualname}.{item.name}" if parent_qualname else item.name
            )
            classes.extend(_parse_classes(item.body, source, func_parent))
    return classes


def parse_classes(
    node: ast.AST,
    source: str,
    parent_qualname: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Public wrapper for ``_parse_classes`` using ``node.body``."""

    return _parse_classes(getattr(node, "body", []), source, parent_qualname)


def _call_name(node: ast.AST) -> Optional[str]:
    """Return a dotted name for ``node`` if it represents a callable expression."""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: List[str] = [node.attr]
        value = node.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        elif isinstance(value, ast.Call):
            inner = _call_name(value.func)
            if inner:
                parts.append(inner)
        elif isinstance(value, ast.Constant):
            if isinstance(value.value, str):
                parts.append(str(value.value))
        else:
            return None
        return ".".join(reversed(parts))
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return None


class _CallCollector(ast.NodeVisitor):
    """Collect function and method call names within a node."""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def visit_Call(self, node: ast.Call) -> None:  # pragma: no cover - ast.NodeVisitor interface
        name = _call_name(node.func)
        if name:
            self.calls.append(name)
        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            if keyword.value is not None:
                self.visit(keyword.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # pragma: no cover - handled by parse_function
        # Skip nested function definitions; they are processed separately.
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # pragma: no cover - handled by parse_function
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # pragma: no cover - defensive
        return


def parse_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source: str,
    parent_qualname: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a dictionary describing ``node`` and any nested definitions."""

    qualname = f"{parent_qualname}.{node.name}" if parent_qualname else node.name
    func_info: Dict[str, Any] = {
        "name": node.name,
        "signature": _format_signature(node),
        "returns": ast.unparse(node.returns) if node.returns else None,
        "docstring": ast.get_docstring(node),
        "source": ast.get_source_segment(source, node),
        "subfunctions": [],
        "subclasses": [],
        "qualname": qualname,
    }

    collector = _CallCollector()
    for stmt in node.body:
        collector.visit(stmt)
    # Preserve ordering while removing duplicates.
    seen: set[str] = set()
    ordered_calls: List[str] = []
    for call in collector.calls:
        if call not in seen:
            ordered_calls.append(call)
            seen.add(call)
    func_info["calls"] = ordered_calls

    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_info["subfunctions"].append(parse_function(item, source, qualname))

    func_info["subclasses"] = _parse_classes(node.body, source, qualname)

    return func_info


def parse_class(
    node: ast.ClassDef,
    source: str,
    parent_qualname: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a dictionary describing ``node`` and any nested classes."""

    qualname = f"{parent_qualname}.{node.name}" if parent_qualname else node.name
    cls_info: Dict[str, Any] = {
        "name": node.name,
        "docstring": ast.get_docstring(node),
        "methods": [],
        "subclasses": [],
        "source": ast.get_source_segment(source, node),
        "qualname": qualname,
    }

    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cls_info["methods"].append(parse_function(item, source, qualname))

    cls_info["subclasses"] = _parse_classes(node.body, source, qualname)

    return cls_info


def parse_python_file(path: str) -> Dict[str, Any]:
    """Parse a Python source file and return structured information.

    Parameters
    ----------
    path:
        File to parse.

    Returns
    -------
    dict
        Dictionary containing module docstring, classes, and functions.
    """

    source = Path(path).read_text(encoding="utf-8")
    module = ast.parse(source)

    parsed: Dict[str, Any] = {
        "module_docstring": ast.get_docstring(module),
        "classes": [],
        "functions": [],
    }

    for node in module.body:
        if isinstance(node, ast.ClassDef):
            parsed["classes"].append(parse_class(node, source))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parsed["functions"].append(parse_function(node, source))

    return parsed




