"""Persistent cache for build detail data (manifest, summary, release tag)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DetailEntry:
    """Cached detail data for a single run."""

    manifest_json: str | None
    summary_text: str | None
    release_tag: str | None


class DetailCache:
    """Persistent cache for build details, keyed by repo + run_id + updated_at.

    Stores at most ``max_per_repo`` entries per repository (FIFO eviction).
    """

    def __init__(self, path: Path, *, max_per_repo: int = 5) -> None:
        self._path = path
        self._max_per_repo = max_per_repo
        self._data: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load detail cache %s: %s", self._path, exc)

    def save(self) -> None:
        """Persist cache to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to save detail cache %s: %s", self._path, exc)

    def get(self, repo_key: str, run_id: int, updated_at: str) -> DetailEntry | None:
        """Look up cached detail data. Returns None on miss."""
        entries = self._data.get(repo_key, [])
        for entry in entries:
            if entry.get("run_id") == run_id and entry.get("updated_at") == updated_at:
                return DetailEntry(
                    manifest_json=entry.get("manifest_json"),
                    summary_text=entry.get("summary_text"),
                    release_tag=entry.get("release_tag"),
                )
        return None

    def put(self, repo_key: str, run_id: int, updated_at: str, entry: DetailEntry) -> None:
        """Store detail data, evicting oldest entries if over limit."""
        entries = self._data.setdefault(repo_key, [])
        entries[:] = [e for e in entries if e.get("run_id") != run_id]
        entries.append({
            "run_id": run_id,
            "updated_at": updated_at,
            "manifest_json": entry.manifest_json,
            "summary_text": entry.summary_text,
            "release_tag": entry.release_tag,
        })
        if len(entries) > self._max_per_repo:
            entries[:] = entries[-self._max_per_repo:]

    def clear_repo(self, repo_key: str) -> None:
        """Remove all cached entries for a specific repo."""
        self._data.pop(repo_key, None)

    def clear_all(self) -> None:
        """Remove all cached entries."""
        self._data.clear()
