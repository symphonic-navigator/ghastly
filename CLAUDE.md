# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the TUI
uv run ghastly

# Dev setup
uv sync
uv run ghastly init          # interactive setup wizard
uv run ghastly add <url>     # append a repo to config

# Tests
uv run pytest tests/ -v
uv run pytest tests/test_config.py::test_name -v   # single test

# Lint / type-check
uv run ruff check src/
uv run mypy
```

## Architecture

**ghastly** is a terminal TUI for monitoring GitHub Actions across repos. Key layers:

| File | Role |
|------|------|
| `cli.py` | Typer entry point (`ghastly`, `ghastly init`, `ghastly add`) |
| `app.py` | `GhastlyApp` — Textual TUI, polling loop, config watcher, keybindings |
| `api.py` | `GitHubClient` — httpx, ETag caching, state diffing, rerun trigger |
| `config.py` | TOML load/write, `Config` / `RepoConfig` dataclasses |
| `notifications.py` | Textual toast + `notify-send` bridge |
| `schema.py` | Parses `ghastly/v1` artifact manifests from step-summary HTML comments |
| `widgets/repo_row.py` | One row per repo — live age timer, status colours, highlight on transition |
| `widgets/detail_panel.py` | Lazy-loaded detail view (artifacts, step summary, fallback to release tag) |
| `widgets/filter_bar.py` | Live fuzzy search over alias / group / status |
| `widgets/group_header.py` | Collapsible group row with aggregate worst-status indicator |

### Data flow

1. `GhastlyApp.on_mount()` starts an `asyncio.gather` polling loop (per-repo, parallel) and a `watchfiles` config watcher.
2. Each poll cycle calls `GitHubClient.get_latest_run()` — ETag conditional request, state diff vs. persisted JSON, update `RepoRow.run` reactive.
3. Reactive changes trigger `_refresh_all()` on the row, add a 2 s `highlighted` CSS class, and fire notifications on state transitions.
4. Detail panel loads lazily on `Enter` — never during polling.

### Key design decisions

- **ETag key**: `owner/repo?branch=<branch or empty>`
- **State diffing**: transition = `run_id` changed OR `display_status` changed
- **Adaptive layout**: width < 120 cols → modal detail; ≥ 120 → split. Overridden by `display.detail_layout` in config.
- **Config append**: `append_repo_to_config()` raw-appends TOML without re-serialising (preserves comments/formatting).
- **Per-repo errors** never crash the app — `asyncio.gather(return_exceptions=True)` everywhere.
- **mypy strict mode** is enabled — keep all public functions typed.

### XDG paths

| Path | Purpose |
|------|---------|
| `~/.config/ghastly/config.toml` | Repos, PAT, preferences |
| `~/.local/share/ghastly/state.json` | Persisted run states for diffing |
| `~/.local/share/ghastly/etags.json` | HTTP ETags |
| `~/.local/share/ghastly/ghastly.log` | File-based log (level from config, default WARNING) |

### CSS / widget conventions

- CSS classes: kebab-case (`.col-alias`, `.build-success`, `.highlighted`)
- Widget IDs: kebab-case (`.repo-{safe-id}`, `#detail-panel`, `#filter-bar`)
- Action methods: `action_*`, reactive watchers: `watch_*`
- `VerticalScroll` from `textual.containers` (not `ScrollView` — removed in 0.80+)
