import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from html_writer import write_index, write_module_page


def test_write_index(tmp_path: Path) -> None:
    links = [("module1", "module1.html"), ("module2", "module2.html")]
    write_index(str(tmp_path), "Project summary", links)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Project summary" in html
    assert "module1.html" in html
    assert "<h1>Project Documentation" in html


def test_write_module_page(tmp_path: Path) -> None:
    links = [("index", "index.html")]
    module_data = {
        "name": "module1",
        "summary": "Module summary",
        "classes": [
            {
                "name": "Bar",
                "summary": "Class summary",
                "docstring": "Bar docs",
                "methods": [
                    {
                        "name": "baz",
                        "signature": "def baz(self): pass",
                        "docstring": "Baz docs",
                        "source": "def baz(self):\n    pass",
                    }
                ],
            }
        ],
        "functions": [
            {
                "name": "foo",
                "signature": "def foo(): pass",
                "summary": "Func summary",
                "docstring": "Foo docs",
                "source": "def foo():\n    pass",
            }
        ],
    }
    write_module_page(str(tmp_path), module_data, links)
    html = (tmp_path / "module1.html").read_text(encoding="utf-8")
    assert "Module summary" in html
    assert "<h2 id=\"Bar\">Class: Bar</h2>" in html
    assert "Bar docs" in html
    assert "Method: def baz(self): pass" in html
    assert "Baz docs" in html
    assert "Func summary" in html
    assert "<h2>Functions" in html
    assert "def foo(): pass" in html
    assert html.count("<pre><code>") == 2
