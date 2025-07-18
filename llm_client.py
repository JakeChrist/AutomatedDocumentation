"""Interface to the local LLM backend required by the SRS.

Handles communication with LMStudio to obtain summaries.
"""

from __future__ import annotations

import time
from typing import Any, Dict

import requests
from requests.exceptions import HTTPError, RequestException


def sanitize_summary(text: str) -> str:
    """Return ``text`` with unprofessional phrases removed."""

    bad_phrases = [
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
    ]

    lines = text.strip().splitlines()
    filtered = [
        line
        for line in lines
        if not any(p in line.lower() for p in bad_phrases)
    ]
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

        prompt = f"""
You are a documentation engine.

Summarize the purpose and contents of the code file below.

❌ Do not:
- Explain how to run the code
- Suggest improvements or extensions
- Include example usage
- Address the reader (e.g., no “you can…” or “note that…”)
- Use phrases like “this script”, “the code above”, or “here’s how it works”

✅ Do:
- Begin directly with what the file does
- State what is implemented (e.g., “Defines a class...", “Implements Conway’s Game of Life...”)
- Mention any algorithms, classes, or patterns used
- Keep it to 1–3 factual sentences

Code:
```python
{text}
```
"""

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a documentation engine."},
                {"role": "user", "content": prompt},
            ],
        }

        error_message = ""
        for _ in range(3):
            try:
                response = requests.post(self.endpoint, json=payload, timeout=None)
                response.raise_for_status()
                data = response.json()
                raw = data["choices"][0]["message"]["content"]
                cleaned = sanitize_summary(raw)
                return cleaned
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



