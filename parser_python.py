"""Parser for Python files used by DocGen-LM.

Uses the `ast` module to extract structures according to the SRS.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List


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


def parse_function(node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> Dict[str, Any]:
    """Return a dictionary describing ``node`` and any nested functions."""

    func_info: Dict[str, Any] = {
        "name": node.name,
        "signature": _format_signature(node),
        "returns": ast.unparse(node.returns) if node.returns else None,
        "docstring": ast.get_docstring(node),
        "source": ast.get_source_segment(source, node),
        "subfunctions": [],
    }

    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_info["subfunctions"].append(parse_function(item, source))

    return func_info


def parse_class(node: ast.ClassDef, source: str) -> Dict[str, Any]:
    """Return a dictionary describing ``node`` and any nested classes."""

    cls_info: Dict[str, Any] = {
        "name": node.name,
        "docstring": ast.get_docstring(node),
        "methods": [],
        "subclasses": [],
        "source": ast.get_source_segment(source, node),
    }

    for item in node.body:
        if isinstance(item, ast.ClassDef):
            cls_info["subclasses"].append(parse_class(item, source))
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cls_info["methods"].append(parse_function(item, source))

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




