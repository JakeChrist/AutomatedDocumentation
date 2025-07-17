"""Simple on-disk cache for LLM responses.

Required to avoid unnecessary calls per the SRS."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional


class ResponseCache:
    """Persist mappings from stable keys to LLM responses."""

    def __init__(self, path: str) -> None:
        self.file = Path(path)
        if self.file.exists():
            try:
                self._data: Dict[str, str] = json.loads(self.file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._data = {}
        else:
            self._data = {}

    @staticmethod
    def make_key(file_path: str, content: str) -> str:
        """Return a deterministic key for *file_path* and *content*."""
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"{file_path}:{digest}"

    def get(self, key: str) -> Optional[str]:
        """Return the cached value for ``key`` if present."""
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        """Store ``value`` under ``key`` and persist to disk."""
        self._data[key] = value
        self._save()

    def _save(self) -> None:
        self.file.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")

