"""Command line interface for DocGen-LM.

This script scans a source tree for Python and MATLAB files, parses them,
requests summaries from a running LLM, and writes HTML documentation.

Examples
--------
Generate documentation for ``./project`` into ``./docs`` while ignoring
``tests`` and ``build`` directories::

    python docgenerator.py ./project --output ./docs --ignore tests --ignore build
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from cache import ResponseCache
from html_writer import write_index, write_module_page
from llm_client import LLMClient
from parser_python import parse_python_file
from parser_matlab import parse_matlab_file
from scanner import scan_directory


def _summarize(client: LLMClient, cache: ResponseCache, key: str, text: str, prompt: str) -> str:
    cached = cache.get(key)
    if cached is not None:
        return cached
    summary = client.summarize(text, prompt)
    cache.set(key, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate HTML documentation using a local LLM")
    parser.add_argument("source", help="Path to the source directory")
    parser.add_argument("--output", required=True, help="Destination directory for HTML output")
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="Paths relative to source that should be ignored (repeatable)",
    )
    parser.add_argument(
        "--llm-url",
        default="http://localhost:1234",
        help="Base URL of the LLM API",
    )
    parser.add_argument(
        "--model",
        default="local",
        help="Model name to use when contacting the LLM",
    )
    args = parser.parse_args(argv)

    client = LLMClient(base_url=args.llm_url, model=args.model)
    try:
        client.ping()
    except ConnectionError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    static_dir = Path(__file__).parent / "static"
    # use absolute path so execution works from any current working directory
    shutil.copytree(static_dir, output_dir / "static", dirs_exist_ok=True)

    cache = ResponseCache(str(output_dir / "cache.json"))

    files = scan_directory(args.source, args.ignore)
    modules = []
    for path in files:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:  # skip files with invalid encoding
            print(f"Skipping {path}: {exc}", file=sys.stderr)
            continue

        try:
            if path.endswith(".py"):
                parsed = parse_python_file(path)
                language = "python"
            else:
                parsed = parse_matlab_file(path)
                language = "matlab"
        except SyntaxError as exc:  # malformed file should be ignored
            print(f"Skipping {path}: {exc}", file=sys.stderr)
            continue

        key = ResponseCache.make_key(path, text)
        summary = _summarize(client, cache, key, text, "module-summary")

        module = {"name": Path(path).stem, "language": language, "summary": summary}
        module.update(parsed)

        # generate summaries for individual classes
        for cls in module.get("classes", []):
            cls_text = cls.get("docstring") or cls.get("name", "")
            cls_key = ResponseCache.make_key(f"{path}:{cls.get('name')}", cls_text)
            cls_summary = _summarize(client, cache, cls_key, cls_text, "class-summary")
            cls["summary"] = cls_summary

        # and for standalone functions
        for func in module.get("functions", []):
            func_text = func.get("signature") or func.get("name", "")
            func_key = ResponseCache.make_key(f"{path}:{func.get('name')}", func_text)
            func_summary = _summarize(client, cache, func_key, func_text, "function-summary")
            func["summary"] = func_summary

        modules.append(module)

    page_links = [(m["name"], f"{m['name']}.html") for m in modules]

    project_text = "\n".join(Path(p).name for p in files)
    project_key = ResponseCache.make_key("PROJECT", project_text)
    project_summary = _summarize(client, cache, project_key, project_text, "project-summary")

    write_index(str(output_dir), project_summary, page_links)
    for module in modules:
        write_module_page(str(output_dir), module, page_links)

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
