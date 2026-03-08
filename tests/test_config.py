"""Unit tests for ghastly.config — config loading and manipulation."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghastly.config import (
    Config,
    RepoConfig,
    append_repo_to_config,
    load_config,
)


def _write_config(path: Path, content: str) -> None:
    """Write content to a TOML config file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


MINIMAL_TOML = """\
[auth]
pat = "ghp_testtoken123"
"""

FULL_TOML = """\
[auth]
pat = "ghp_testtoken123"

[display]
detail_layout = "split"
poll_interval = 30

[notifications]
on_success = true
on_failure = true
on_cancelled = true
system_notify = false

[[repos]]
url = "https://github.com/owner/my-service"
alias = "my-service"
group = "work"
watch_branch = "main"
artifact_hint = "auto"
"""


def test_load_valid_config(tmp_path: Path) -> None:
    """A valid config.toml loads into a Config dataclass correctly."""
    config_file = tmp_path / "config.toml"
    _write_config(config_file, FULL_TOML)

    config = load_config(config_file)

    assert isinstance(config, Config)
    assert config.auth.pat == "ghp_testtoken123"
    assert config.display.detail_layout == "split"
    assert config.display.poll_interval == 30
    assert config.notifications.on_cancelled is True
    assert config.notifications.system_notify is False
    assert len(config.repos) == 1
    assert config.repos[0].url == "https://github.com/owner/my-service"
    assert config.repos[0].group == "work"


def test_missing_file(tmp_path: Path) -> None:
    """Loading a non-existent config file raises FileNotFoundError."""
    missing = tmp_path / "nonexistent" / "config.toml"
    with pytest.raises(FileNotFoundError):
        load_config(missing)


def test_missing_pat(tmp_path: Path) -> None:
    """A config file with an empty PAT raises ValueError."""
    config_file = tmp_path / "config.toml"
    _write_config(config_file, "[auth]\npat = \"\"\n")

    with pytest.raises(ValueError, match="pat"):
        load_config(config_file)


def test_repo_key(tmp_path: Path) -> None:
    """RepoConfig.key returns 'owner/repo' derived from the URL."""
    config_file = tmp_path / "config.toml"
    _write_config(config_file, FULL_TOML)

    config = load_config(config_file)
    repo = config.repos[0]

    assert repo.key == "owner/my-service"
    assert repo.owner == "owner"
    assert repo.repo == "my-service"


def test_append_repo(tmp_path: Path) -> None:
    """append_repo_to_config adds a [[repos]] entry to an existing config."""
    config_file = tmp_path / "config.toml"
    _write_config(config_file, MINIMAL_TOML)

    new_repo = RepoConfig(
        url="https://github.com/org/new-service",
        alias="new-service",
        group="personal",
    )
    append_repo_to_config(new_repo, path=config_file)

    # Reload and verify the repo was appended
    config = load_config(config_file)
    assert len(config.repos) == 1
    appended = config.repos[0]
    assert appended.url == "https://github.com/org/new-service"
    assert appended.group == "personal"
