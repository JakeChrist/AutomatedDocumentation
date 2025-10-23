from pathlib import Path

from parser_javascript import parse_javascript_file, parse_typescript_file


def test_parse_simple_javascript(tmp_path: Path) -> None:
    source = tmp_path / "utils.js"
    source.write_text(
        "// Utilities for the project\n\n"
        "/** Calculate the sum */\n"
        "export function add(a, b) {\n"
        "    return a + b;\n"
        "}\n\n"
        "// Double the value\n"
        "export const double = (value) => value * 2;\n\n"
        "/** Helper tools */\n"
        "export class Helper {\n"
        "    /** Build a helper */\n"
        "    build(data) {\n"
        "        return data;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    result = parse_javascript_file(str(source))

    assert result["module_docstring"] == "Utilities for the project"
    assert [f["name"] for f in result["functions"]] == ["add", "double"]
    assert result["functions"][0]["docstring"] == "Calculate the sum"
    assert "return a + b" in result["functions"][0]["source"]
    assert result["classes"][0]["name"] == "Helper"
    assert result["classes"][0]["docstring"] == "Helper tools"
    assert [m["name"] for m in result["classes"][0]["methods"]] == ["build"]


def test_parse_simple_typescript(tmp_path: Path) -> None:
    source = tmp_path / "types.ts"
    source.write_text(
        "/** Type helpers */\n"
        "export function greet(name: string): string {\n"
        "    return `Hello ${name}`;\n"
        "}\n\n"
        "export const identity = (value: number): number => value;\n\n"
        "export class Person {\n"
        "    /** Create a new person */\n"
        "    constructor(private name: string) {}\n\n"
        "    /** Say hello */\n"
        "    greet(): string {\n"
        "        return `Hi ${this.name}`;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    result = parse_typescript_file(str(source))

    assert result["module_docstring"] == "Type helpers"
    assert [f["name"] for f in result["functions"]] == ["greet", "identity"]
    assert result["functions"][1]["signature"] == "identity(value: number)"
    assert result["classes"][0]["name"] == "Person"
    method_signatures = [m["signature"] for m in result["classes"][0]["methods"]]
    assert "constructor(private name: string)" in method_signatures[0]
    assert any(sig.startswith("greet()") for sig in method_signatures)
