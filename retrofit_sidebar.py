#!/usr/bin/env python3
"""Retrofit documentation sidebars with a hierarchical module list."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from bs4 import BeautifulSoup

import scanner


def _paths_to_tree(paths: list[str]) -> Dict[str, Any]:
    """Convert a list of file paths into a nested dictionary tree."""
    tree: Dict[str, Any] = {}
    for path in paths:
        parts = Path(path).parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault(parts[-1], None)
    return tree


def _tree_to_ul(tree: Dict[str, Any], soup: BeautifulSoup) -> Any:
    """Recursively build ``<ul>`` elements from *tree*."""
    ul = soup.new_tag("ul")
    for name in sorted(tree):
        li = soup.new_tag("li")
        li.string = name
        child = tree[name]
        if isinstance(child, dict) and child:
            li.append(_tree_to_ul(child, soup))
        ul.append(li)
    return ul


def retrofit_sidebar(source_root: str, docs_dir: str) -> None:
    """Replace documentation sidebars with a hierarchical module list."""
    base = Path(source_root).resolve()
    modules = scanner.scan_directory(str(base), ignore=[])
    relative = [str(Path(p).resolve().relative_to(base)) for p in modules]
    tree = _paths_to_tree(relative)

    soup = BeautifulSoup("", "html.parser")
    sidebar_markup = str(_tree_to_ul(tree, soup))

    docs_path = Path(docs_dir)
    for html_file in docs_path.glob("*.html"):
        html_soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
        sidebar = html_soup.find("div", class_="sidebar")
        if sidebar is not None:
            sidebar.replace_with(BeautifulSoup(sidebar_markup, "html.parser"))
            html_file.write_text(str(html_soup), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace docs sidebar with hierarchical module list."
    )
    parser.add_argument("--source", default=".", help="Source root directory")
    parser.add_argument("--docs", default="Docs", help="Documentation directory")
    args = parser.parse_args()
    retrofit_sidebar(args.source, args.docs)


if __name__ == "__main__":
    main()
