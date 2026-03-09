"""ghastly CLI — entry point for all commands and TUI launch."""

from __future__ import annotations

import asyncio
import json as _json
from datetime import UTC, datetime
from typing import Annotated

import typer

app = typer.Typer(
    name="ghastly",
    help="GitHub Actions watcher — terminal-native build monitor.",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Launch the ghastly TUI, or run a subcommand."""
    if ctx.invoked_subcommand is None:
        _launch_tui()


def _launch_tui() -> None:
    """Load config and start the Textual TUI."""
    from .config import CONFIG_PATH, load_config

    try:
        config = load_config(CONFIG_PATH)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        typer.echo("Run `ghastly init` to set up your configuration.", err=True)
        raise typer.Exit(1) from exc
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Error loading config: {exc}", err=True)
        raise typer.Exit(1) from exc

    from .app import GhastlyApp

    tui_app = GhastlyApp(config)
    tui_app.run()


@app.command()
def init() -> None:
    """Interactive setup wizard: configure PAT and add first repo."""
    from .config import CONFIG_PATH, DATA_DIR, write_config

    typer.echo("Welcome to ghastly — GitHub Actions watcher 👻")
    typer.echo("=" * 50)
    typer.echo()

    # PAT input
    pat = typer.prompt(
        "Enter your GitHub Personal Access Token (PAT)",
        hide_input=True,
    ).strip()

    if not pat:
        typer.echo("PAT cannot be empty.", err=True)
        raise typer.Exit(1)

    # Validate PAT
    typer.echo("Validating PAT... ", nl=False)
    login = asyncio.run(_validate_pat(pat))
    if not login:
        typer.echo("FAILED", err=True)
        typer.echo(
            "Could not authenticate with GitHub. "
            "Check your PAT has 'repo' and 'actions:read' scopes.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(f"OK (authenticated as {login})")
    typer.echo()

    # First repo URL
    repo_url = typer.prompt(
        "Enter the GitHub repository URL to watch (e.g. https://github.com/owner/repo)",
    ).strip()

    from .config import RepoConfig

    try:
        repo = RepoConfig(url=repo_url)
        _ = repo.owner  # Validate URL is parseable
        _ = repo.repo
    except (ValueError, IndexError) as exc:
        typer.echo(f"Invalid repository URL: {exc}", err=True)
        raise typer.Exit(1) from exc

    alias = typer.prompt(
        f"Alias for this repo (leave blank to use '{repo.repo}')",
        default="",
    ).strip()
    if alias:
        repo.alias = alias

    group = typer.prompt(
        "Group name (leave blank for 'default')",
        default="",
    ).strip()
    if group:
        repo.group = group

    branch = typer.prompt(
        "Branch to watch (leave blank for default branch)",
        default="",
    ).strip()
    if branch:
        repo.watch_branch = branch

    # Write config
    config_data: dict[str, object] = {
        "auth": {"pat": pat},
        "display": {"detail_layout": "auto", "poll_interval": 60},
        "notifications": {
            "on_success": True,
            "on_failure": True,
            "on_cancelled": False,
            "system_notify": True,
        },
        "repos": [
            {
                "url": repo.url,
                "alias": repo.alias,
                "group": repo.group,
                "watch_branch": repo.watch_branch,
                "artifact_hint": "auto",
            }
        ],
    }

    write_config(config_data, CONFIG_PATH)

    # Create data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Remind user to secure the config file
    typer.echo()
    typer.echo(f"Config written to {CONFIG_PATH}")
    typer.echo(f"Data directory: {DATA_DIR}")
    typer.echo()
    typer.echo("Security tip: run the following to protect your PAT:")
    typer.echo(f"  chmod 600 {CONFIG_PATH}")
    typer.echo()
    typer.echo("Run `ghastly` to launch the TUI.")


@app.command()
def add(
    url: str = typer.Argument(..., help="GitHub repository URL"),
    alias: Annotated[str | None, typer.Option("--alias", "-a", help="Display alias")] = None,
    group: Annotated[str | None, typer.Option("--group", "-g", help="Group name")] = None,
    branch: Annotated[
        str | None, typer.Option("--branch", "-b", help="Branch to watch")
    ] = None,
) -> None:
    """Add a repository to the watch list."""
    from .config import CONFIG_PATH, RepoConfig, append_repo_to_config

    repo = RepoConfig(
        url=url.strip(),
        alias=alias or "",
        group=group or "default",
        watch_branch=branch or "",
    )

    try:
        _ = repo.owner
        _ = repo.repo
    except (ValueError, IndexError) as exc:
        typer.echo(f"Invalid repository URL: {exc}", err=True)
        raise typer.Exit(1) from exc

    if not CONFIG_PATH.exists():
        typer.echo(
            f"Config file not found at {CONFIG_PATH}. Run `ghastly init` first.", err=True
        )
        raise typer.Exit(1)

    from .config import load_config

    existing = load_config(CONFIG_PATH)
    if any(r.url.rstrip("/") == repo.url.rstrip("/") for r in existing.repos):
        typer.echo(f"Repository already in watch list: {repo.url}", err=True)
        raise typer.Exit(1)

    append_repo_to_config(repo, CONFIG_PATH)
    typer.echo(f"Added {repo.alias} ({repo.url}) to config.")
    typer.echo("If ghastly is running, the new repo will appear automatically.")


@app.command(name="list")
def list_repos() -> None:
    """List all watched repositories with their indices."""
    from .config import CONFIG_PATH, load_config

    if not CONFIG_PATH.exists():
        typer.echo(f"Config file not found at {CONFIG_PATH}. Run `ghastly init` first.", err=True)
        raise typer.Exit(1)

    config = load_config(CONFIG_PATH)
    if not config.repos:
        typer.echo("No repositories configured.")
        return

    # Column widths
    w_alias = max(len(r.alias or r.repo) for r in config.repos)
    w_key = max(len(r.key) for r in config.repos)
    w_group = max(len(r.group or "default") for r in config.repos)

    header = f"  {'#':>3}  {'alias':<{w_alias}}  {'repo':<{w_key}}  {'group':<{w_group}}  branch"
    typer.echo(header)
    typer.echo("  " + "-" * (len(header) - 2))

    for idx, repo in enumerate(config.repos):
        alias = repo.alias or repo.repo
        group = repo.group or "default"
        branch = repo.watch_branch or "(default)"
        typer.echo(f"  {idx:>3}  {alias:<{w_alias}}  {repo.key:<{w_key}}  {group:<{w_group}}  {branch}")


def _age_short(iso: str) -> str:
    """Return a compact age string like '2h 15m' or '45m' from an ISO timestamp."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = datetime.now(tz=UTC) - dt
    total = max(0, int(delta.total_seconds()))
    mins = total // 60
    hours = mins // 60
    days = hours // 24
    if days >= 1:
        return f"{days}d {hours % 24}h"
    if hours >= 1:
        return f"{hours}h {mins % 60}m"
    return f"{mins}m"


@app.command()
def status(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Show current build status of all watched repositories."""
    from .config import CONFIG_PATH, STATE_PATH, load_config

    if not CONFIG_PATH.exists():
        typer.echo(
            f"Config file not found at {CONFIG_PATH}. Run `ghastly init` first.", err=True
        )
        raise typer.Exit(1)

    config = load_config(CONFIG_PATH)

    state: dict[str, object] = {}
    import contextlib
    if STATE_PATH.exists():
        with contextlib.suppress(Exception):
            state = _json.loads(STATE_PATH.read_text(encoding="utf-8"))

    repos_out = []
    counts: dict[str, int] = {"success": 0, "failure": 0, "running": 0, "other": 0}

    for repo in config.repos:
        s = state.get(repo.key)
        s = s if isinstance(s, dict) else {}
        display_status = str(s.get("display_status", "unknown"))

        if display_status == "success":
            counts["success"] += 1
        elif display_status == "failure":
            counts["failure"] += 1
        elif display_status in ("in_progress", "queued"):
            counts["running"] += 1
        else:
            counts["other"] += 1

        commit_raw = str(s.get("head_commit_message") or "")
        commit = commit_raw.replace("\n", " ").strip()

        repos_out.append({
            "key": repo.key,
            "alias": repo.alias or repo.repo,
            "group": repo.group or "default",
            "status": display_status,
            "branch": str(s.get("head_branch") or repo.watch_branch or ""),
            "commit": commit,
            "updated_at": str(s.get("updated_at") or ""),
            "url": str(s.get("html_url") or ""),
        })

    if json_output:
        typer.echo(_json.dumps({
            "total": len(repos_out),
            "passing": counts["success"],
            "failing": counts["failure"],
            "running": counts["running"],
            "repos": repos_out,
        }, indent=2))
        return

    if not repos_out:
        typer.echo("No repositories configured.")
        return

    w_alias = max(len(r["alias"]) for r in repos_out)
    w_status = max(len(r["status"]) for r in repos_out)
    w_branch = max((len(r["branch"]) for r in repos_out), default=6)
    w_age = 8

    header = (
        f"  {'ALIAS':<{w_alias}}  {'STATUS':<{w_status}}  "
        f"{'AGE':<{w_age}}  {'BRANCH':<{w_branch}}  COMMIT"
    )
    typer.echo(header)
    typer.echo("  " + "─" * (len(header) - 2))

    _STATUS_COLOURS = {
        "success": typer.colors.GREEN,
        "failure": typer.colors.RED,
        "in_progress": typer.colors.YELLOW,
        "queued": typer.colors.YELLOW,
    }

    for r in repos_out:
        st = r["status"]
        colour = _STATUS_COLOURS.get(st)
        status_text = typer.style(st, fg=colour) if colour else st
        # Pad after the coloured text so columns stay aligned
        status_padding = " " * max(0, w_status - len(st))

        age = _age_short(r["updated_at"])
        branch = r["branch"] or "—"
        commit = r["commit"]
        if len(commit) > 52:
            commit = commit[:49] + "…"

        typer.echo(
            f"  {r['alias']:<{w_alias}}  {status_text}{status_padding}  "
            f"{age:<{w_age}}  {branch:<{w_branch}}  {commit}"
        )

    typer.echo()
    summary: list[str] = []
    if counts["success"]:
        summary.append(typer.style(f"{counts['success']} passing", fg=typer.colors.GREEN))
    if counts["failure"]:
        summary.append(typer.style(f"{counts['failure']} failing", fg=typer.colors.RED))
    if counts["running"]:
        summary.append(typer.style(f"{counts['running']} running", fg=typer.colors.YELLOW))
    if counts["other"]:
        summary.append(f"{counts['other']} other")
    typer.echo("  " + "  ·  ".join(summary))


def _resolve_repo_key(identifier: str) -> str | None:
    """Resolve an index, URL, or owner/repo string to a repo key. Returns None if not found."""
    from .config import CONFIG_PATH, load_config

    config = load_config(CONFIG_PATH)

    # Try as integer index
    try:
        idx = int(identifier)
        if 0 <= idx < len(config.repos):
            return config.repos[idx].key
        return None
    except ValueError:
        pass

    # Try as full URL
    url = identifier.rstrip("/")
    for repo in config.repos:
        if repo.url.rstrip("/") == url:
            return repo.key

    # Try as owner/repo key
    for repo in config.repos:
        if repo.key == identifier:
            return repo.key

    return None


@app.command()
def delete(
    identifier: Annotated[str, typer.Argument(help="Index, URL, or owner/repo of the repo to remove")],
) -> None:
    """Remove a repository from the watch list."""
    from .config import CONFIG_PATH, remove_repo_from_config

    if not CONFIG_PATH.exists():
        typer.echo(f"Config file not found at {CONFIG_PATH}. Run `ghastly init` first.", err=True)
        raise typer.Exit(1)

    key = _resolve_repo_key(identifier)
    if key is None:
        typer.echo(f"Repository not found: {identifier}", err=True)
        raise typer.Exit(1)

    remove_repo_from_config(key, CONFIG_PATH)
    typer.echo(f"Removed {key} from config.")
    typer.echo("If ghastly is running, the repo will disappear automatically.")


@app.command(name="set-group")
def set_group(
    identifier: Annotated[str, typer.Argument(help="Index, URL, or owner/repo")],
    group: Annotated[str, typer.Argument(help="Group name")],
) -> None:
    """Set the group of a watched repository."""
    from .config import CONFIG_PATH, update_repo_in_config

    if not CONFIG_PATH.exists():
        typer.echo(f"Config file not found at {CONFIG_PATH}. Run `ghastly init` first.", err=True)
        raise typer.Exit(1)

    key = _resolve_repo_key(identifier)
    if key is None:
        typer.echo(f"Repository not found: {identifier}", err=True)
        raise typer.Exit(1)

    update_repo_in_config(key, {"group": group}, CONFIG_PATH)
    typer.echo(f"Set group of {key} to '{group}'.")


@app.command(name="unset-group")
def unset_group(
    identifier: Annotated[str, typer.Argument(help="Index, URL, or owner/repo")],
) -> None:
    """Remove a repository from its group (resets to 'default')."""
    from .config import CONFIG_PATH, update_repo_in_config

    if not CONFIG_PATH.exists():
        typer.echo(f"Config file not found at {CONFIG_PATH}. Run `ghastly init` first.", err=True)
        raise typer.Exit(1)

    key = _resolve_repo_key(identifier)
    if key is None:
        typer.echo(f"Repository not found: {identifier}", err=True)
        raise typer.Exit(1)

    update_repo_in_config(key, {"group": "default"}, CONFIG_PATH)
    typer.echo(f"Removed {key} from its group (now in 'default').")


@app.command(name="clear-cache")
def clear_cache(
    repo: str = typer.Argument("", help="Repo key (owner/repo) to clear, or empty for all"),
) -> None:
    """Clear the build detail cache and manifest hints."""
    from .config import DETAIL_CACHE_PATH, MANIFEST_HINTS_PATH
    from .detail_cache import DetailCache
    from .manifest_hints import ManifestHints

    dc = DetailCache(DETAIL_CACHE_PATH)
    mh = ManifestHints(MANIFEST_HINTS_PATH)

    if repo:
        dc.clear_repo(repo)
        mh.clear_repo(repo)
        dc.save()
        mh.save()
        typer.echo(f"Cache cleared for {repo}")
    else:
        dc.clear_all()
        mh.clear_all()
        dc.save()
        mh.save()
        typer.echo("All caches cleared")


@app.command(name="alias")
def set_alias(
    identifier: Annotated[str, typer.Argument(help="Index, URL, or owner/repo")],
    name: Annotated[str, typer.Argument(help="New alias")],
) -> None:
    """Set the display alias of a watched repository."""
    from .config import CONFIG_PATH, update_repo_in_config

    if not CONFIG_PATH.exists():
        typer.echo(f"Config file not found at {CONFIG_PATH}. Run `ghastly init` first.", err=True)
        raise typer.Exit(1)

    key = _resolve_repo_key(identifier)
    if key is None:
        typer.echo(f"Repository not found: {identifier}", err=True)
        raise typer.Exit(1)

    update_repo_in_config(key, {"alias": name}, CONFIG_PATH)
    typer.echo(f"Alias of {key} set to '{name}'.")


async def _validate_pat(pat: str) -> str | None:
    """Call GET /user to validate the PAT. Returns login name or None."""
    import httpx

    try:
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        ) as client:
            resp = await client.get("/user")
            if resp.status_code == 200:
                return str(resp.json().get("login", ""))
            return None
    except Exception:  # noqa: BLE001
        return None
