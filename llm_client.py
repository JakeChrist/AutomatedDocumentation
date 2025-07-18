"""Interface to the local LLM backend required by the SRS.

Handles communication with LMStudio to obtain summaries.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict

import requests
from requests.exceptions import HTTPError, RequestException

# Prompt definitions for the documentation model
SYSTEM_PROMPT = (
    "You are not an assistant. "
    "You are a documentation engine that generates factual summaries of code files. "
    "Do not help the user. Do not refer to yourself. Do not explain what you are doing. "
    "Only describe what the code defines or implements."
)

USER_PROMPT = (
    "Summarize the code below.\n\n"
    "- Do not refer to yourself, the summary, or the response.\n"
    "- Do not include instructions, usage advice, or disclaimers.\n"
    "- Do not say what is or isn't included in the code.\n"
    "- Do not explain how to run it.\n"
    "- Do not use phrases like \"this script\", \"the code above\", or \"you can\".\n"
    "- Just describe what is implemented in the file.\n\n"
    "Code:\n```python\n{text}\n```"
)


def sanitize_summary(text: str) -> str:
    """Return ``text`` with meta commentary removed."""

    BAD_START_PHRASES = [
        "you can",
        "note that",
        "the code above",
        "this script",
        "here's how",
        "to run this",
        "let's",
        "for example",
        "you might",
        "we can",
        "should you",
        "if you want",
        "the summary",
        "this explanation",
        "this output",
        "this description",
        "this response",
    ]

    lines = text.strip().splitlines()
    filtered = []
    for line in lines:
        line_lower = line.strip().lower()
        if any(line_lower.startswith(p) for p in BAD_START_PHRASES):
            continue
        if (
            "this summary" in line_lower
            or "this output" in line_lower
            or "this response" in line_lower
            or "does not include" in line_lower
            or "avoids addressing" in line_lower
        ):
            continue
        if re.match(r"^this (script|code|file) (does|is)\b", line_lower):
            continue
        filtered.append(line.strip())

    return "\n".join(filtered).strip()


class LLMClient:
    """Thin wrapper around the LMStudio HTTP API."""

    def __init__(self, base_url: str = "http://localhost:1234", model: str = "local") -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/v1/chat/completions"
        self.model = model

    def ping(self, timeout: float = 2.0) -> bool:
        """Return ``True`` if the API is reachable.

        Raises
        ------
        ConnectionError
            If the server cannot be contacted.
        """

        try:
            response = requests.get(self.base_url, timeout=timeout)
            response.raise_for_status()
            return True
        except RequestException as exc:
            raise ConnectionError(f"Unable to reach LMStudio at {self.base_url}") from exc

    def summarize(self, text: str, prompt_type: str) -> str:
        """Return a summary for ``text``."""

        prompt = USER_PROMPT.format(text=text)

        payload: Dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }

        error_message = ""
        for _ in range(3):
            try:
                response = requests.post(self.endpoint, json=payload, timeout=None)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return sanitize_summary(content)
            except HTTPError as exc:
                resp = exc.response or response
                try:
                    err_json = resp.json()
                    if isinstance(err_json, dict):
                        error_message = err_json.get("error", resp.text)
                    else:
                        error_message = resp.text
                except ValueError:
                    error_message = resp.text
                time.sleep(1)
            except RequestException as exc:
                error_message = str(exc)
                time.sleep(1)

        raise RuntimeError(f"LLM request failed: {error_message}")



