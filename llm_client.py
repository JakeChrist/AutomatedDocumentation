"""Interface to the local LLM backend required by the SRS.

Handles communication with LMStudio to obtain summaries.
"""

from __future__ import annotations

import time
from typing import Any, Dict

import requests
from requests.exceptions import RequestException


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
        """Return a summary for ``text`` using the supplied ``prompt_type``."""

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt_type},
                {"role": "user", "content": text},
            ],
        }

        for _ in range(3):
            try:
                response = requests.post(self.endpoint, json=payload, timeout=30)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            except RequestException:
                time.sleep(1)

        raise RuntimeError("LLM request failed")



