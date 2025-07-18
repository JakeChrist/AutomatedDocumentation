import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from html_writer import write_index, write_module_page


def test_write_index(tmp_path: Path) -> None:
    links = [("module<1>", "module1.html"), ("module&2", "module2.html")]
    summaries = {"module<1>": "First module.", "module&2": ""}
    write_index(str(tmp_path), "Project <summary> & data", links, summaries)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Project &lt;summary&gt; &amp; data" in html
    assert html.count("module1.html") == 2
    assert html.count("module2.html") == 2
    assert "module&lt;1&gt;" in html
    assert "module&amp;2" in html
    assert "<h2>Modules" in html
    assert "<ul" in html
    assert "<small>First module." in html
    # only one summary should be rendered
    assert html.count("<small>") == 1
    assert "<h1>Project Documentation" in html


def test_write_module_page(tmp_path: Path) -> None:
    links = [("index", "index.html")]
    module_data = {
        "name": "module1",
        "summary": "Module <summary>",
        "classes": [
            {
                "name": "Bar",
                "summary": "Class <summary>",
                "docstring": "Bar docs & stuff",
                "methods": [
                    {
                        "name": "baz",
                        "signature": "def baz(self): pass",
                        "docstring": "Baz <docs>",
                        "source": "def baz(self):\n    pass",
                    }
                ],
            }
        ],
        "functions": [
            {
                "name": "foo",
                "signature": "def foo(): pass",
                "summary": "Func summary & stuff",
                "docstring": "Foo docs",
                "source": "def foo():\n    pass",
            }
        ],
    }
    write_module_page(str(tmp_path), module_data, links)
    html = (tmp_path / "module1.html").read_text(encoding="utf-8")
    assert "Module &lt;summary&gt;" in html
    assert "<h2 id=\"Bar\">Class: Bar</h2>" in html
    assert "Bar docs &amp; stuff" in html
    assert "Method: def baz(self): pass" in html
    assert "Baz &lt;docs&gt;" in html
    assert "Func summary &amp; stuff" in html
    assert "<h2>Functions" in html
    assert "def foo(): pass" in html
    assert html.count("<pre><code>") == 2
