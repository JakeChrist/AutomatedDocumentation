import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from pathlib import Path

import pytest

from scanner import scan_directory


def create_files(base: Path, files: list[str]) -> None:
    for rel in files:
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")


def test_scan_directory_ignore_folder(tmp_path: Path) -> None:
    create_files(
        tmp_path,
        [
            "a.py",
            "b.m",
            "c.txt",
            os.path.join("sub", "d.py"),
            os.path.join("ignore_me", "e.py"),
        ],
    )

    result = scan_directory(str(tmp_path), ["ignore_me"])

    expected = {
        str(tmp_path / "a.py"),
        str(tmp_path / "b.m"),
        str(tmp_path / "sub" / "d.py"),
    }
    assert set(result) == expected


def test_scan_directory_mixed_file_types(tmp_path: Path) -> None:
    create_files(
        tmp_path,
        [
            "one.py",
            "two.m",
            "three.txt",
            os.path.join("nested", "four.py"),
            os.path.join("nested", "five.md"),
            os.path.join("nested", "six.m"),
        ],
    )

    result = scan_directory(str(tmp_path), [])

    expected = {
        str(tmp_path / "one.py"),
        str(tmp_path / "two.m"),
        str(tmp_path / "nested" / "four.py"),
        str(tmp_path / "nested" / "six.m"),
    }
    assert set(result) == expected
