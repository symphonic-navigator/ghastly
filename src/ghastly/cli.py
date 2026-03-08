"""ghastly CLI — entry point for all commands and TUI launch."""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

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
    alias: Annotated[Optional[str], typer.Option("--alias", "-a", help="Display alias")] = None,
    group: Annotated[Optional[str], typer.Option("--group", "-g", help="Group name")] = None,
    branch: Annotated[
        Optional[str], typer.Option("--branch", "-b", help="Branch to watch")
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
