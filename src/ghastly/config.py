"""Config loading and validation for ghastly."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".config" / "ghastly" / "config.toml"
DATA_DIR = Path.home() / ".local" / "share" / "ghastly"
STATE_PATH = DATA_DIR / "state.json"
ETAGS_PATH = DATA_DIR / "etags.json"
LOG_PATH = DATA_DIR / "ghastly.log"


@dataclass
class RepoConfig:
    """Configuration for a single watched repository."""

    url: str
    alias: str = ""
    group: str = "default"
    watch_branch: str = ""
    artifact_hint: str = "auto"  # "auto" | "latest" | "releases"

    def __post_init__(self) -> None:
        # Derive alias from URL if not set
        if not self.alias:
            self.alias = self.url.rstrip("/").split("/")[-1]

    @property
    def owner(self) -> str:
        """Extract owner from GitHub URL."""
        parts = self.url.rstrip("/").split("/")
        if len(parts) < 2:
            raise ValueError(f"Cannot parse owner from URL: {self.url}")
        return parts[-2]

    @property
    def repo(self) -> str:
        """Extract repo name from GitHub URL."""
        return self.url.rstrip("/").split("/")[-1]

    @property
    def key(self) -> str:
        """Unique key for this repo (owner/repo)."""
        return f"{self.owner}/{self.repo}"


@dataclass
class AuthConfig:
    """Authentication configuration."""

    pat: str


@dataclass
class DisplayConfig:
    """Display configuration."""

    detail_layout: str = "auto"  # "auto" | "modal" | "split"
    poll_interval: int = 60
    theme: str = "textual-dark"


@dataclass
class NotificationsConfig:
    """Notifications configuration."""

    on_success: bool = True
    on_failure: bool = True
    on_cancelled: bool = False
    system_notify: bool = True


@dataclass
class Config:
    """Full ghastly configuration."""

    auth: AuthConfig
    display: DisplayConfig = field(default_factory=DisplayConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    repos: list[RepoConfig] = field(default_factory=list)
    log_level: str = "WARNING"


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load and validate config from a TOML file."""
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Run `ghastly init` to create your configuration."
        )

    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    # Auth — required
    auth_raw = raw.get("auth", {})
    pat = auth_raw.get("pat", "").strip()
    if not pat:
        raise ValueError("Config is missing [auth] pat — run `ghastly init`.")
    auth = AuthConfig(pat=pat)

    # Display — optional with defaults
    display_raw = raw.get("display", {})
    display = DisplayConfig(
        detail_layout=display_raw.get("detail_layout", "auto"),
        poll_interval=int(display_raw.get("poll_interval", 60)),
        theme=display_raw.get("theme", "textual-dark"),
    )

    # Notifications — optional with defaults
    notif_raw = raw.get("notifications", {})
    notifications = NotificationsConfig(
        on_success=bool(notif_raw.get("on_success", True)),
        on_failure=bool(notif_raw.get("on_failure", True)),
        on_cancelled=bool(notif_raw.get("on_cancelled", False)),
        system_notify=bool(notif_raw.get("system_notify", True)),
    )

    # Repos — optional list
    repos: list[RepoConfig] = []
    for repo_raw in raw.get("repos", []):
        url = repo_raw.get("url", "").strip()
        if not url:
            logger.warning("Skipping repo entry with no URL")
            continue
        repos.append(
            RepoConfig(
                url=url,
                alias=repo_raw.get("alias", ""),
                group=repo_raw.get("group", "default"),
                watch_branch=repo_raw.get("watch_branch", ""),
                artifact_hint=repo_raw.get("artifact_hint", "auto"),
            )
        )

    log_level = str(raw.get("log_level", "WARNING")).upper()

    return Config(
        auth=auth,
        display=display,
        notifications=notifications,
        repos=repos,
        log_level=log_level,
    )


def write_config(config_data: dict[str, object], path: Path = CONFIG_PATH) -> None:
    """Write config dict to TOML file, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    # [auth]
    auth = config_data.get("auth", {})
    if isinstance(auth, dict):
        lines.append("[auth]")
        lines.append(f'pat = "{auth.get("pat", "")}"')
        lines.append("")

    # [display]
    display = config_data.get("display", {})
    if isinstance(display, dict):
        lines.append("[display]")
        lines.append(f'detail_layout = "{display.get("detail_layout", "auto")}"')
        lines.append(f'poll_interval = {display.get("poll_interval", 60)}')
        lines.append(f'theme = "{display.get("theme", "textual-dark")}"')
        lines.append("")

    # [notifications]
    notif = config_data.get("notifications", {})
    if isinstance(notif, dict):
        lines.append("[notifications]")
        lines.append(f'on_success = {str(notif.get("on_success", True)).lower()}')
        lines.append(f'on_failure = {str(notif.get("on_failure", True)).lower()}')
        lines.append(f'on_cancelled = {str(notif.get("on_cancelled", False)).lower()}')
        lines.append(f'system_notify = {str(notif.get("system_notify", True)).lower()}')
        lines.append("")

    # [[repos]]
    repos = config_data.get("repos", [])
    if isinstance(repos, list):
        for repo in repos:
            if not isinstance(repo, dict):
                continue
            lines.append("[[repos]]")
            lines.append(f'url = "{repo.get("url", "")}"')
            if repo.get("alias"):
                lines.append(f'alias = "{repo["alias"]}"')
            if repo.get("group"):
                lines.append(f'group = "{repo["group"]}"')
            if repo.get("watch_branch"):
                lines.append(f'watch_branch = "{repo["watch_branch"]}"')
            artifact_hint = repo.get("artifact_hint", "auto")
            lines.append(f'artifact_hint = "{artifact_hint}"')
            lines.append("")

    content = "\n".join(lines)
    path.write_text(content, encoding="utf-8")
    logger.info("Config written to %s", path)


def append_repo_to_config(
    repo: RepoConfig,
    path: Path = CONFIG_PATH,
) -> None:
    """Append a repo entry to an existing config file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "",
        "[[repos]]",
        f'url = "{repo.url}"',
    ]
    if repo.alias and repo.alias != repo.repo:
        lines.append(f'alias = "{repo.alias}"')
    if repo.group and repo.group != "default":
        lines.append(f'group = "{repo.group}"')
    if repo.watch_branch:
        lines.append(f'watch_branch = "{repo.watch_branch}"')
    if repo.artifact_hint != "auto":
        lines.append(f'artifact_hint = "{repo.artifact_hint}"')

    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    logger.info("Appended repo %s to config", repo.url)


def config_to_dict(config: "Config") -> dict[str, object]:
    """Serialise a Config object to a dict suitable for write_config."""
    repos: list[dict[str, object]] = []
    for repo in config.repos:
        entry: dict[str, object] = {"url": repo.url}
        if repo.alias and repo.alias != repo.repo:
            entry["alias"] = repo.alias
        if repo.group:
            entry["group"] = repo.group
        if repo.watch_branch:
            entry["watch_branch"] = repo.watch_branch
        entry["artifact_hint"] = repo.artifact_hint
        repos.append(entry)

    return {
        "auth": {"pat": config.auth.pat},
        "display": {
            "detail_layout": config.display.detail_layout,
            "poll_interval": config.display.poll_interval,
            "theme": config.display.theme,
        },
        "notifications": {
            "on_success": config.notifications.on_success,
            "on_failure": config.notifications.on_failure,
            "on_cancelled": config.notifications.on_cancelled,
            "system_notify": config.notifications.system_notify,
        },
        "repos": repos,
    }


def update_repo_in_config(
    key: str,
    updates: dict[str, object],
    path: Path = CONFIG_PATH,
) -> bool:
    """Load config, apply field updates to the repo identified by key, write back.

    Returns True if the repo was found and updated.
    """
    config = load_config(path)
    for repo in config.repos:
        if repo.key == key:
            for attr, value in updates.items():
                setattr(repo, attr, value)
            write_config(config_to_dict(config), path)
            return True
    return False


def remove_repo_from_config(key: str, path: Path = CONFIG_PATH) -> bool:
    """Remove the repo identified by key from the config. Returns True if found."""
    config = load_config(path)
    original_count = len(config.repos)
    config.repos = [r for r in config.repos if r.key != key]
    if len(config.repos) == original_count:
        return False
    write_config(config_to_dict(config), path)
    return True
