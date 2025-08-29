"""Source file discovery for DocGen-LM.

Implements recursive scanning with ignore rules as described in the SRS.
"""

from __future__ import annotations

from pathlib import Path
import os
from typing import List

try:  # optional dependency
    from tqdm import tqdm
except ImportError:  # pragma: no cover - fallback when tqdm is missing
    def tqdm(iterable, **kwargs):  # type: ignore
        return iterable


def _is_subpath(path: Path, parent: Path) -> bool:
    """Return True if *path* is equal to or inside *parent*."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def scan_directory(base_path: str, ignore: List[str], show_progress: bool = False) -> List[str]:
    """Recursively discover ``.py``, ``.m``, ``.cpp``, ``.h``, and ``.java`` files under *base_path*.

    Parameters
    ----------
    base_path:
        Directory to search.
    ignore:
        List of paths (relative to ``base_path``) that should be skipped.
    show_progress:
        If True, display a progress bar while scanning.
    Returns
    -------
    list[str]
        Absolute paths to discovered source files.
    """
    base = Path(base_path).resolve()
    ignore_paths = {(base / p).resolve() for p in ignore}
    results: List[str] = []

    walker = os.walk(base, topdown=True)
    if show_progress:
        walker = tqdm(walker, desc="Scanning sources")

    for root, dirs, files in walker:
        root_path = Path(root)
        # prune ignored directories and internal .git folders
        dirs[:] = [
            d
            for d in dirs
            if d != ".git" and not any(_is_subpath(root_path / d, ig) for ig in ignore_paths)
        ]

        for name in files:
            if not name.endswith((".py", ".m", ".cpp", ".h", ".java")):
                continue
            file_path = root_path / name
            if any(_is_subpath(file_path, ig) for ig in ignore_paths):
                continue
            results.append(str(file_path))

    return sorted(results)
