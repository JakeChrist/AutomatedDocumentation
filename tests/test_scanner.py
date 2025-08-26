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


def test_scan_directory_skips_git_folder(tmp_path: Path) -> None:
    create_files(
        tmp_path,
        [
            "good.py",
            os.path.join(".git", "ignored.py"),
            os.path.join(".git", "sub", "also.py"),
        ],
    )

    result = scan_directory(str(tmp_path), [])

    assert str(tmp_path / "good.py") in result
    assert not any(".git" in p for p in result)


def test_scan_directory_supports_cpp_h_java(tmp_path: Path) -> None:
    create_files(
        tmp_path,
        [
            "main.cpp",
            "header.h",
            "Program.java",
            os.path.join("nested", "util.cpp"),
            os.path.join("nested", "helper.h"),
            os.path.join("nested", "Example.java"),
            "skip.txt",
        ],
    )

    result = scan_directory(str(tmp_path), [])

    expected = {
        str(tmp_path / "main.cpp"),
        str(tmp_path / "header.h"),
        str(tmp_path / "Program.java"),
        str(tmp_path / "nested" / "util.cpp"),
        str(tmp_path / "nested" / "helper.h"),
        str(tmp_path / "nested" / "Example.java"),
    }
    assert set(result) == expected
