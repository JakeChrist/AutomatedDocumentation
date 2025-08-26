import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from parser_java import parse_java_file


def test_parse_java(tmp_path: Path) -> None:
    src = textwrap.dedent(
        """
        /** Example package */
        package demo;

        /** Utility class */
        public class Util {
            /** public field */
            public int count;

            /** do work */
            public void work() {}
        }
        """
    )
    file = tmp_path / "Sample.java"
    file.write_text(src)

    result = parse_java_file(str(file))
    assert result["module_docstring"] == "Example package"
    assert result.get("package") == "demo"
    assert result["functions"] == []
    assert len(result["classes"]) == 1
    cls = result["classes"][0]
    assert cls["name"] == "Util"
    assert cls["docstring"] == "Utility class"
    field = cls["variables"][0]
    assert field["name"] == "count"
    assert field["docstring"] == "public field"
    assert field["type"] == "int"
    assert "public int count;" in field["source"]
    method = cls["methods"][0]
    assert method["name"] == "work"
    assert method["docstring"] == "do work"
    assert "public void work" in method["source"]
