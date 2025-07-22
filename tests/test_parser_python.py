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
            """Add two numbers."""
            return x + y

        class Greeter:
            """Says hi."""

            def greet(self, name: str = "World") -> str:
                """Return a greeting."""
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
    method = cls["methods"][0]
    assert method["signature"] == "greet(self, name: str='World') -> str"
    assert method["docstring"] == "Return a greeting."
    assert "def greet" in method["source"]
    assert "Return a greeting." in method["source"]

    assert len(result["functions"]) == 1
    func = result["functions"][0]
    assert func["name"] == "add"
    assert func["signature"] == "add(x: int, y: int) -> int"
    assert func["returns"] == "int"
    assert func["docstring"] == "Add two numbers."
    assert "def add" in func["source"]
    assert "Add two numbers." in func["source"]


def test_parse_complex_signature(tmp_path: Path) -> None:
    src = textwrap.dedent(
        '''
        """Docstring."""

        def complex(a, /, b, *, c: int = 1, **kw) -> None:
            """Complex function."""
            pass
        '''
    )
    file = tmp_path / "sample.py"
    file.write_text(src)

    result = parse_python_file(str(file))

    sig = result["functions"][0]["signature"]
    func = result["functions"][0]
    assert sig == "complex(a/, b, *, c: int=1, **kw) -> None"
    assert func["docstring"] == "Complex function."
    assert "Complex function." in func["source"]


def test_parse_nested_structures(tmp_path: Path) -> None:
    src = textwrap.dedent(
        '''
        def outer(x):
            def inner(y):
                return y * 2
            return inner(x)

        class A:
            class B:
                def method(self):
                    pass
        '''
    )
    file = tmp_path / "sample.py"
    file.write_text(src)

    result = parse_python_file(str(file))

    outer = result["functions"][0]
    assert outer["name"] == "outer"
    assert len(outer.get("subfunctions", [])) == 1
    assert outer["subfunctions"][0]["name"] == "inner"
    assert "def inner" in outer["subfunctions"][0]["source"]

    cls = result["classes"][0]
    assert cls["name"] == "A"
    assert len(cls.get("subclasses", [])) == 1
    sub = cls["subclasses"][0]
    assert sub["name"] == "B"
    assert len(sub.get("methods", [])) == 1
    assert sub["methods"][0]["name"] == "method"


def test_deeply_nested_classes(tmp_path: Path) -> None:
    src = textwrap.dedent(
        '''
        class A:
            class B:
                class C:
                    def inner(self):
                        pass
        '''
    )
    file = tmp_path / "deep.py"
    file.write_text(src)

    result = parse_python_file(str(file))

    a = result["classes"][0]
    b = a["subclasses"][0]
    c = b["subclasses"][0]
    assert c["name"] == "C"
    assert c["methods"][0]["name"] == "inner"


def test_class_inside_method(tmp_path: Path) -> None:
    src = textwrap.dedent(
        '''
        class A:
            def outer(self):
                class B:
                    def m(self):
                        pass
        '''
    )
    file = tmp_path / "inner.py"
    file.write_text(src)

    result = parse_python_file(str(file))

    a = result["classes"][0]
    assert len(a["subclasses"]) == 1
    b = a["subclasses"][0]
    assert b["name"] == "B"
    assert b["methods"][0]["name"] == "m"

