"""Simple on-disk cache for LLM responses.

Required to avoid unnecessary calls per the SRS."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional


class ResponseCache:
    """Persist mappings from stable keys to LLM responses."""

    def __init__(self, path: str) -> None:
        self.file = Path(path)
        if self.file.exists():
            try:
                self._data: Dict[str, Any] = json.loads(
                    self.file.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                self._data = {}
        else:
            self._data = {}
        # ensure progress map exists
        self._data.setdefault("__progress__", {})

    @staticmethod
    def make_key(file_path: str, content: Optional[str]) -> str:
        """Return a deterministic key for *file_path* and *content*."""
        to_hash = "<None>" if content is None else content
        digest = hashlib.sha256(to_hash.encode("utf-8")).hexdigest()
        return f"{file_path}:{digest}"

    def get(self, key: str) -> Optional[str]:
        """Return the cached value for ``key`` if present."""
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        """Store ``value`` under ``key`` and persist to disk."""
        self._data[key] = value
        self._save()

    def get_progress(self) -> Dict[str, Any]:
        """Return the mapping of processed module paths to their data."""
        progress = self._data.get("__progress__", {})
        # return a shallow copy to prevent accidental mutation
        return dict(progress)

    def set_progress_entry(self, path: str, module_data: Dict[str, Any]) -> None:
        """Record ``module_data`` for ``path`` in the progress map."""
        progress = self._data.setdefault("__progress__", {})
        progress[path] = module_data
        self._save()

    def clear_progress(self) -> None:
        """Remove all saved progress information."""
        self._data["__progress__"] = {}
        self._save()

    def _save(self) -> None:
        self.file.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")

