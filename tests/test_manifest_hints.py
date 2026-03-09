"""Unit tests for ghastly.manifest_hints — persistent manifest location hints."""

from __future__ import annotations

from pathlib import Path

from ghastly.manifest_hints import ManifestHints


def test_store_and_retrieve_summary_job(tmp_path: Path) -> None:
    """A stored summary job name can be retrieved."""
    hints = ManifestHints(tmp_path / "hints.json")
    hints.set_summary_job("owner/repo", "build-api")
    assert hints.get_summary_job("owner/repo") == "build-api"


def test_miss_returns_none(tmp_path: Path) -> None:
    """Unknown repo returns None."""
    hints = ManifestHints(tmp_path / "hints.json")
    assert hints.get_summary_job("owner/unknown") is None


def test_persistence(tmp_path: Path) -> None:
    """Hints survive save/reload."""
    path = tmp_path / "hints.json"
    h1 = ManifestHints(path)
    h1.set_summary_job("owner/repo", "deploy")
    h1.save()

    h2 = ManifestHints(path)
    assert h2.get_summary_job("owner/repo") == "deploy"


def test_clear_repo(tmp_path: Path) -> None:
    """clear_repo removes hints for one repo only."""
    hints = ManifestHints(tmp_path / "hints.json")
    hints.set_summary_job("owner/a", "job-a")
    hints.set_summary_job("owner/b", "job-b")
    hints.clear_repo("owner/a")
    assert hints.get_summary_job("owner/a") is None
    assert hints.get_summary_job("owner/b") == "job-b"


def test_clear_all(tmp_path: Path) -> None:
    """clear_all removes everything."""
    hints = ManifestHints(tmp_path / "hints.json")
    hints.set_summary_job("owner/a", "job-a")
    hints.set_summary_job("owner/b", "job-b")
    hints.clear_all()
    assert hints.get_summary_job("owner/a") is None
    assert hints.get_summary_job("owner/b") is None


def test_update_overwrites(tmp_path: Path) -> None:
    """Setting a hint again overwrites the previous value."""
    hints = ManifestHints(tmp_path / "hints.json")
    hints.set_summary_job("owner/repo", "old-job")
    hints.set_summary_job("owner/repo", "new-job")
    assert hints.get_summary_job("owner/repo") == "new-job"
