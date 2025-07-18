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
from llm_client import LLMClient, sanitize_summary
from parser_python import parse_python_file
from parser_matlab import parse_matlab_file
from scanner import scan_directory

def _summarize(client: LLMClient, cache: ResponseCache, key: str, text: str, prompt_type: str) -> str:
    cached = cache.get(key)
    if cached is not None:
        return cached
    summary = client.summarize(text, prompt_type)
    cache.set(key, summary)
    return summary


DOC_PROMPT = (
    "You are a documentation engine.\n\n"
    "Generate a technical summary of the function or class below.\n"
    "- Do not include suggestions or conversational language.\n"
    "- Do not say \"this function\", \"you can\", or \"the following code\".\n"
    "- Do not refer to the instructions or docstring.\n"
    "- Just describe what the code implements, in 1–3 concise sentences.\n\n"
    "Code:\n```python\n"
    "{source}\n"
    "Docstring (optional):\n"
    '\"\"\"{docstring}\"\"\"\n'
    "```"
)


def _build_function_prompt(
    source: str,
    class_name: str | None = None,
    class_summary: str | None = None,
    project_summary: str | None = None,
) -> str:
    """Return a context-enriched prompt for summarizing ``source``."""

    lines = ["You are a documentation generator."]
    if class_name:
        lines.append(f"The following function is part of the class `{class_name}`.")
    if class_summary:
        lines.append(f"This class {class_summary}")
    if project_summary:
        lines.append(f"This project {project_summary}")
    lines.extend(
        [
            "Summarize the function based on its source code below.",
            "- Do not include assistant phrasing or usage instructions.",
            "- Do not mention unrelated games or systems.",
            "- Only use the context and code provided.",
            "",
            "```python",
            source,
            "```",
        ]
    )
    return "\n".join(lines)


def _rewrite_docstring(
    client: LLMClient,
    cache: ResponseCache,
    file_path: str,
    item: dict[str, str],
    *,
    class_name: str | None = None,
    class_summary: str | None = None,
    project_summary: str | None = None,
) -> None:
    """Rewrite ``item`` docstring using optional context."""

    source = item.get("source", "")
    docstring = item.get("docstring", "") or ""
    if not source and not docstring:
        print(
            f"Warning: no source or docstring for {file_path}:{item.get('name')}",
            file=sys.stderr,
        )
        return

    if class_name or class_summary or project_summary:
        prompt = _build_function_prompt(
            source,
            class_name=class_name,
            class_summary=class_summary,
            project_summary=project_summary,
        )
        key_content = source + (class_name or "") + (class_summary or "") + (project_summary or "")
    else:
        prompt = DOC_PROMPT.format(source=source, docstring=docstring)
        key_content = source + docstring

    key = ResponseCache.make_key(
        f"REWRITE:{file_path}:{item.get('name')}",
        key_content,
    )
    result = _summarize(client, cache, key, prompt, "docstring")
    item["docstring"] = sanitize_summary(result) or "No summary available."


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
        summary = _summarize(client, cache, key, text, "module")

        module = {
            "name": Path(path).stem,
            "language": language,
            "summary": summary,
            "filename": Path(path).name,
            "path": path,
        }
        module.update(parsed)

        # generate summaries for individual classes
        for cls in module.get("classes", []):
            cls_text = cls.get("docstring") or cls.get("name", "")
            cls_key = ResponseCache.make_key(f"{path}:{cls.get('name')}", cls_text)
            cls_summary = _summarize(client, cache, cls_key, cls_text, "class")
            cls["summary"] = cls_summary
            _rewrite_docstring(client, cache, path, cls)

        # and for standalone functions (summarized later with project context)
        for func in module.get("functions", []):
            func["summary"] = ""

        modules.append(module)

    page_links = [(m["name"], f"{m['name']}.html") for m in modules]

    project_lines = ["Project structure:"]
    for mod in modules:
        project_lines.append(f"- {mod['filename']}")
        classes = mod.get("classes", []) or []
        functions = mod.get("functions", []) or []

        if not classes and not functions:
            print(
                f"Warning: {mod['filename']} has no classes or functions",
                file=sys.stderr,
            )
            project_lines.append("  - (no classes or functions defined)")
            continue

        for cls in classes:
            project_lines.append(f"  - Class: {cls.get('name', '')}")
            method_names = [m.get("name", "") for m in cls.get("methods", [])]
            methods_text = ", ".join(method_names) if method_names else "(none)"
            project_lines.append(f"    - Methods: {methods_text}")

        if functions:
            func_names = ", ".join(f.get("name", "") for f in functions)
            project_lines.append(f"  - Functions: {func_names}")

    project_outline = "\n".join(project_lines)

    # gather markdown documentation
    md_files = []
    readme = Path(args.source) / "README.md"
    if readme.exists():
        md_files.append(readme)
    for p in Path(args.source).rglob('*'):
        if p.is_dir() and p.name.lower() == 'docs':
            for md in p.rglob('*.md'):
                md_files.append(md)

    md_parts = []
    for md_file in md_files:
        try:
            md_parts.append(md_file.read_text(encoding='utf-8'))
        except Exception as exc:  # pragma: no cover - filesystem edge case
            print(f"Skipping {md_file}: {exc}", file=sys.stderr)

    md_context = "\n".join(md_parts).strip()
    readme_summary = ""
    if md_context:
        readme_key = ResponseCache.make_key("README", md_context)
        readme_summary = _summarize(client, cache, readme_key, md_context, "readme")
        readme_summary = sanitize_summary(readme_summary)

    PROJECT_PROMPT = f"""
Summarize the purpose of this codebase in 1–2 sentences.

- Base your answer only on the provided structure.
- Do not address the reader or give usage advice.
- Do not say "the code defines" or "this summary".
- Prefer concise technical descriptions of what is implemented.
- Feel free to group related functionality (e.g., grid setup, game loop).

Structure:
{project_outline}
"""

    project_key = ResponseCache.make_key("PROJECT", project_outline)
    raw_summary = _summarize(client, cache, project_key, PROJECT_PROMPT, "docstring")
    project_summary = sanitize_summary(raw_summary)
    if readme_summary:
        project_summary = f"{readme_summary}\n{project_summary}".strip()

    # Now that the project summary is available, generate function summaries
    # and rewrite method/function docstrings with context.
    for module in modules:
        path = module.get("path", "")
        for cls in module.get("classes", []):
            for method in cls.get("methods", []):
                _rewrite_docstring(
                    client,
                    cache,
                    path,
                    method,
                    class_name=cls.get("name"),
                    class_summary=cls.get("summary"),
                    project_summary=project_summary,
                )
        for func in module.get("functions", []):
            src = func.get("source") or func.get("signature") or func.get("name", "")
            prompt = _build_function_prompt(src, project_summary=project_summary)
            func_key = ResponseCache.make_key(f"{path}:{func.get('name')}", prompt)
            func_summary = _summarize(client, cache, func_key, prompt, "docstring")
            func["summary"] = func_summary
            _rewrite_docstring(
                client,
                cache,
                path,
                func,
                project_summary=project_summary,
            )

    module_summaries = {m["name"]: m.get("summary", "") for m in modules}
    write_index(str(output_dir), project_summary, page_links, module_summaries)
    for module in modules:
        write_module_page(str(output_dir), module, page_links)

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
