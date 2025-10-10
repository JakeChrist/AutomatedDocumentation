import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from parser_matlab import parse_matlab_file


def test_parse_simple_matlab(tmp_path: Path) -> None:
    src = textwrap.dedent(
        """
        % Example MATLAB file
        % Another line
        function y = add(x, y)
            y = x + y;
        end
        """
    )
    file = tmp_path / "sample.m"
    file.write_text(src)

    result = parse_matlab_file(str(file))

    assert result["header"] == "Example MATLAB file\nAnother line"
    assert len(result["functions"]) == 1
    func = result["functions"][0]
    assert func["name"] == "add"
    assert func["args"] == ["x", "y"]
    assert "function y = add" in func["signature"]
    expected_source = textwrap.dedent(
        """
        function y = add(x, y)
            y = x + y;
        end
        """
    ).strip()
    assert func["source"] == expected_source


def test_parse_multiple_functions(tmp_path: Path) -> None:
    src = textwrap.dedent(
        """
        function [out1,out2] = compute(a, b)
            out1 = a + b;
            out2 = a - b;
        end

        function result = square(x)
            result = x ^ 2;
        end
        """
    )
    file = tmp_path / "multi.m"
    file.write_text(src)

    result = parse_matlab_file(str(file))

    assert result["header"] == ""
    assert len(result["functions"]) == 2
    names = [f["name"] for f in result["functions"]]
    assert names == ["compute", "square"]
    assert result["functions"][0]["args"] == ["a", "b"]
    assert result["functions"][1]["args"] == ["x"]
