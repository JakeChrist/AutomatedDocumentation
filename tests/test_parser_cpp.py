import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from parser_cpp import parse_cpp_file


def test_parse_cpp(tmp_path: Path) -> None:
    src = textwrap.dedent(
        """
        /** Module comment */
        namespace demo {

        /** Adds numbers */
        int add(int a, int b) {
            return a + b;
        }

        /** Greeter class */
        class Greeter {
        public:
            /// name field
            std::string name;

            /// greet someone
            std::string greet(const std::string& who) {
                return "Hi " + who;
            }
        };
        }
        """
    )
    file = tmp_path / "sample.cpp"
    file.write_text(src)

    result = parse_cpp_file(str(file))
    assert result["module_docstring"] == "Module comment"
    assert result.get("namespace") == "demo"
    assert len(result["functions"]) == 1
    func = result["functions"][0]
    assert func["name"] == "add"
    assert func["docstring"] == "Adds numbers"
    assert "return a + b;" in func["source"]
    assert len(result["classes"]) == 1
    cls = result["classes"][0]
    assert cls["name"] == "Greeter"
    assert cls["docstring"] == "Greeter class"
    field = cls["variables"][0]
    assert field["name"] == "name"
    assert field["docstring"] == "name field"
    assert "std::string name;" in field["source"]
    method = cls["methods"][0]
    assert method["name"] == "greet"
    assert method["docstring"] == "greet someone"
    assert "std::string greet" in method["source"]
