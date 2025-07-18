"""HTML rendering utilities for DocGen-LM.

Renders documentation pages using simple template substitution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Tuple

from pygments import highlight
from pygments.lexers import PythonLexer, MatlabLexer, TextLexer
from pygments.formatters import HtmlFormatter

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "template.html"


def _highlight(code: str, language: str) -> str:
    """Return ``code`` highlighted for ``language`` using pygments."""
    if language.lower() == "matlab":
        lexer = MatlabLexer()
    elif language.lower() == "python":
        lexer = PythonLexer()
    else:
        lexer = TextLexer()
    formatter = HtmlFormatter(noclasses=True)
    return highlight(code, lexer, formatter)


def _render_html(title: str, header: str, body: str, nav_html: str) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        title=title,
        header=header,
        body=body,
        navigation=nav_html,
        static_path="static/style.css",
    )


def write_index(output_dir: str, project_summary: str, page_links: Iterable[Tuple[str, str]]) -> None:
    """Render ``index.html`` with *project_summary* and navigation links."""
    dest_dir = Path(output_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    nav_html = "\n".join(f'<li><a href="{link}">{text}</a></li>' for text, link in page_links)
    body_parts = [f"<p>{project_summary}</p>", "<h2>Modules</h2>", "<ul>", nav_html, "</ul>"]
    body = "\n".join(body_parts)
    html = _render_html("Project Documentation", "Project Documentation", body, nav_html)
    (dest_dir / "index.html").write_text(html, encoding="utf-8")


def write_module_page(output_dir: str, module_data: dict[str, Any], page_links: Iterable[Tuple[str, str]]) -> None:
    """Render a module documentation page using ``module_data``."""
    dest_dir = Path(output_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    module_name = module_data.get("name", "module")
    language = module_data.get("language", "python")
    nav_html = "\n".join(f'<li><a href="{link}">{text}</a></li>' for text, link in page_links)

    body_parts = [f"<p>{module_data.get('summary', '')}</p>"]

    for cls in module_data.get("classes", []):
        cls_name = cls.get("name", "")
        body_parts.append(f'<h2 id="{cls_name}">Class: {cls_name}</h2>')
        doc = cls.get("docstring") or cls.get("summary")
        if doc:
            body_parts.append(f"<p>{doc}</p>")
        for method in cls.get("methods", []):
            sig = method.get("signature") or method.get("name", "")
            body_parts.append(f'<h3 id="{method.get("name")}">Method: {sig}</h3>')
            if method.get("docstring"):
                body_parts.append(f'<p>{method["docstring"]}</p>')
            src = method.get("source")
            if src:
                body_parts.append("<pre><code>")
                body_parts.append(_highlight(src, language))
                body_parts.append("</code></pre>")

    if module_data.get("functions"):
        body_parts.append("<h2>Functions</h2>")
    for func in module_data.get("functions", []):
        sig = func.get("signature") or func.get("name", "")
        body_parts.append(f'<h3 id="{func.get("name")}">{sig}</h3>')
        summary = func.get("summary")
        if summary:
            body_parts.append(f"<p>{summary}</p>")
        src = func.get("source")
        if src:
            body_parts.append("<pre><code>")
            body_parts.append(_highlight(src, language))
            body_parts.append("</code></pre>")

    body = "\n".join(body_parts)
    html = _render_html(module_name, module_name, body, nav_html)
    (dest_dir / f"{module_name}.html").write_text(html, encoding="utf-8")
