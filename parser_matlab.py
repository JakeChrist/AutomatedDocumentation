"""Parser for MATLAB `.m` files used by DocGen-LM.

Employs simple line-based parsing as outlined in the SRS."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List


def parse_matlab_file(path: str) -> Dict[str, Any]:
    """Parse a MATLAB ``.m`` file and extract basic structure.

    Parameters
    ----------
    path:
        File to parse.

    Returns
    -------
    dict
        Dictionary containing the file header comments and any ``function``
        declarations found. Each function entry provides the name of the
        function and a list of arguments.
    """
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()

    # Extract leading comment lines as the file header
    header_lines: List[str] = []
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("%"):
            header_lines.append(stripped.lstrip("% "))
        elif stripped == "":
            # allow blank lines before the header ends
            header_lines.append("") if header_lines else None
        else:
            body_start = i
            break
    else:
        body_start = len(lines)

    header = "\n".join(header_lines).strip()

    func_re = re.compile(
        r"^\s*function\s+(?:\[[^\]]*\]|[^=]+)?=?\s*(\w+)\s*(?:\(([^)]*)\))?",
        re.IGNORECASE,
    )
    functions: List[Dict[str, Any]] = []

    for line in lines[body_start:]:
        m = func_re.match(line)
        if m:
            name = m.group(1)
            args = m.group(2) or ""
            arg_list = [a.strip() for a in args.split(";") if a.strip()] if ";" in args else [a.strip() for a in args.split(",") if a.strip()]
            functions.append({"name": name, "args": arg_list})

    return {"header": header, "functions": functions}
