import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from parser_python import parse_python_file


def test_parse_simple_module(tmp_path: Path) -> None:
    src = textwrap.dedent(
        '''
        """Example module."""

        def add(x: int, y: int) -> int:
            return x + y

        class Greeter:
            """Says hi."""

            def greet(self, name: str = "World") -> str:
                return f"Hello, {name}"
        '''
    )
    file = tmp_path / "sample.py"
    file.write_text(src)

    result = parse_python_file(str(file))

    assert result["module_docstring"] == "Example module."
    assert len(result["classes"]) == 1
    cls = result["classes"][0]
    assert cls["name"] == "Greeter"
    assert cls["docstring"] == "Says hi."
    assert cls["methods"][0]["signature"] == "greet(self, name: str='World') -> str"

    assert len(result["functions"]) == 1
    func = result["functions"][0]
    assert func["name"] == "add"
    assert func["signature"] == "add(x: int, y: int) -> int"
    assert func["returns"] == "int"


def test_parse_complex_signature(tmp_path: Path) -> None:
    src = textwrap.dedent(
        '''
        """Docstring."""

        def complex(a, /, b, *, c: int = 1, **kw) -> None:
            pass
        '''
    )
    file = tmp_path / "sample.py"
    file.write_text(src)

    result = parse_python_file(str(file))

    sig = result["functions"][0]["signature"]
    assert sig == "complex(a/, b, *, c: int=1, **kw) -> None"

