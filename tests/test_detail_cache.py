"""Unit tests for ghastly.detail_cache — persistent build detail caching."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghastly.detail_cache import DetailCache, DetailEntry


def test_store_and_retrieve(tmp_path: Path) -> None:
    """A stored entry can be retrieved by the same cache key."""
    cache = DetailCache(tmp_path / "cache.json")
    entry = DetailEntry(
        manifest_json='{"schema": "ghastly/v1", "artifacts": []}',
        summary_text="## Build passed",
        release_tag=None,
    )
    cache.put("owner/repo", 123, "2026-03-09T10:00:00+00:00", entry)
    result = cache.get("owner/repo", 123, "2026-03-09T10:00:00+00:00")

    assert result is not None
    assert result.summary_text == "## Build passed"
    assert result.manifest_json == '{"schema": "ghastly/v1", "artifacts": []}'


def test_miss_on_different_updated_at(tmp_path: Path) -> None:
    """A different updated_at (re-run) returns None (cache miss)."""
    cache = DetailCache(tmp_path / "cache.json")
    entry = DetailEntry(manifest_json=None, summary_text="old", release_tag=None)
    cache.put("owner/repo", 123, "2026-03-09T10:00:00+00:00", entry)

    result = cache.get("owner/repo", 123, "2026-03-09T11:00:00+00:00")
    assert result is None


def test_miss_on_different_run_id(tmp_path: Path) -> None:
    """A different run_id returns None."""
    cache = DetailCache(tmp_path / "cache.json")
    entry = DetailEntry(manifest_json=None, summary_text="data", release_tag=None)
    cache.put("owner/repo", 123, "2026-03-09T10:00:00+00:00", entry)

    result = cache.get("owner/repo", 456, "2026-03-09T10:00:00+00:00")
    assert result is None


def test_persistence(tmp_path: Path) -> None:
    """Cache persists to disk and survives reload."""
    path = tmp_path / "cache.json"
    cache1 = DetailCache(path)
    entry = DetailEntry(manifest_json=None, summary_text="persistent", release_tag="v1.0")
    cache1.put("owner/repo", 99, "2026-03-09T10:00:00+00:00", entry)
    cache1.save()

    cache2 = DetailCache(path)
    result = cache2.get("owner/repo", 99, "2026-03-09T10:00:00+00:00")
    assert result is not None
    assert result.summary_text == "persistent"
    assert result.release_tag == "v1.0"


def test_eviction_keeps_latest_per_repo(tmp_path: Path) -> None:
    """Only the latest N entries per repo are kept (oldest evicted)."""
    cache = DetailCache(tmp_path / "cache.json", max_per_repo=2)
    for i in range(3):
        cache.put("owner/repo", i, f"2026-03-0{i+1}T10:00:00+00:00",
                  DetailEntry(manifest_json=None, summary_text=f"run-{i}", release_tag=None))

    assert cache.get("owner/repo", 0, "2026-03-01T10:00:00+00:00") is None
    assert cache.get("owner/repo", 1, "2026-03-02T10:00:00+00:00") is not None
    assert cache.get("owner/repo", 2, "2026-03-03T10:00:00+00:00") is not None


def test_clear_repo(tmp_path: Path) -> None:
    """clear_repo removes all entries for one repo, keeps others."""
    cache = DetailCache(tmp_path / "cache.json")
    cache.put("owner/a", 1, "t1", DetailEntry(None, "a", None))
    cache.put("owner/b", 2, "t2", DetailEntry(None, "b", None))

    cache.clear_repo("owner/a")

    assert cache.get("owner/a", 1, "t1") is None
    assert cache.get("owner/b", 2, "t2") is not None


def test_clear_all(tmp_path: Path) -> None:
    """clear_all removes everything."""
    cache = DetailCache(tmp_path / "cache.json")
    cache.put("owner/a", 1, "t1", DetailEntry(None, "a", None))
    cache.put("owner/b", 2, "t2", DetailEntry(None, "b", None))

    cache.clear_all()

    assert cache.get("owner/a", 1, "t1") is None
    assert cache.get("owner/b", 2, "t2") is None
