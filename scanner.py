"""Source file discovery for DocGen-LM.

Implements recursive scanning with ignore rules as described in the SRS.
"""

from __future__ import annotations

from pathlib import Path
import os
from typing import List


def _is_subpath(path: Path, parent: Path) -> bool:
    """Return True if *path* is equal to or inside *parent*."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def scan_directory(base_path: str, ignore: List[str]) -> List[str]:
    """Recursively discover ``.py`` and ``.m`` files under *base_path*.

    Parameters
    ----------
    base_path:
        Directory to search.
    ignore:
        List of paths (relative to ``base_path``) that should be skipped.
    Returns
    -------
    list[str]
        Absolute paths to discovered source files.
    """
    base = Path(base_path).resolve()
    ignore_paths = {(base / p).resolve() for p in ignore}
    results: List[str] = []

    for root, dirs, files in os.walk(base, topdown=True):
        root_path = Path(root)
        # prune ignored directories and internal .git folders
        dirs[:] = [
            d
            for d in dirs
            if d != ".git" and not any(_is_subpath(root_path / d, ig) for ig in ignore_paths)
        ]

        for name in files:
            if not (name.endswith(".py") or name.endswith(".m")):
                continue
            file_path = root_path / name
            if any(_is_subpath(file_path, ig) for ig in ignore_paths):
                continue
            results.append(str(file_path))

    return sorted(results)
