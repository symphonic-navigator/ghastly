"""Persistent hints for manifest/summary locations per repo."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ManifestHints:
    """Remembers which job name contains the step summary for each repo.

    This avoids iterating all jobs on subsequent detail loads — try the
    hinted job first, fall back to full scan only if the hint misses.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load manifest hints %s: %s", self._path, exc)

    def save(self) -> None:
        """Persist hints to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to save manifest hints %s: %s", self._path, exc)

    def get_summary_job(self, repo_key: str) -> str | None:
        """Return the hinted job name for step summary, or None."""
        entry = self._data.get(repo_key)
        if entry:
            return entry.get("summary_job")
        return None

    def set_summary_job(self, repo_key: str, job_name: str) -> None:
        """Record which job name contains the step summary."""
        self._data.setdefault(repo_key, {})["summary_job"] = job_name

    def clear_repo(self, repo_key: str) -> None:
        """Remove all hints for a specific repo."""
        self._data.pop(repo_key, None)

    def clear_all(self) -> None:
        """Remove all hints."""
        self._data.clear()

    def clear(self) -> None:
        """Remove all hints (alias for clear_all)."""
        self._data.clear()
