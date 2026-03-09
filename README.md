# ghastly

```
  __ _  _               _    _
 / _` || |_   __ _  ___| |_ | |_  _
 \__, || ' \ / _` |(_-<|  _|| | || |
 |___/ |_||_|\__,_|/__/ \__||_|\_, |
                                |__/
  ghastly/v1  —  GitHub ActionS waTcher
```

**Terminal-native build monitor for GitHub Actions.**

---

## What is it?

ghastly is a Textual-based TUI dashboard that monitors GitHub Actions across
multiple repositories simultaneously. It is designed for developers running
parallel build sessions who need ambient awareness of build status and artifact
versions without switching context to a browser.

It polls the GitHub API at a configurable interval, fires desktop notifications
on state changes, and optionally parses a structured `ghastly/v1` artifact
manifest embedded in workflow step summaries — surfacing exactly what was built
and at what version.

Each repository row shows:

| Column      | Description                                                             |
|-------------|-------------------------------------------------------------------------|
| alias       | Display name (or repo name if no alias is set)                          |
| branch      | Branch the latest run executed on                                       |
| now         | `running` / `queued` if a run is currently active, otherwise `—`        |
| last build  | Conclusion of the last completed run (success / failure / cancelled)    |
| duration    | Duration of the last completed run, or live elapsed time while running  |
| age         | How long ago the last completed run finished                            |
| commit      | Commit message that triggered the run                                   |

---

## Prerequisites

- Python 3.11 or later
- A GitHub Personal Access Token (PAT) with the following scopes:
  - `repo` and `actions:read` — required
  - `actions:write` — optional, enables run re-trigger (`r` / `R` keys)
- `notify-send` — optional, for system desktop notifications (Linux)

---

## Installation

**pip:**

```sh
pip install ghastly
```

**uv (recommended):**

```sh
uv tool install ghastly
```

**AUR (Arch Linux):**

```sh
yay -S ghastly
```

---

## Quickstart

1. Run the interactive setup wizard:

   ```sh
   ghastly init
   ```

   This prompts for your PAT, validates it against the GitHub API, and adds
   your first repository. Config is written to `~/.config/ghastly/config.toml`.

2. Add further repositories:

   ```sh
   ghastly add https://github.com/owner/repo
   ```

3. Launch the dashboard:

   ```sh
   ghastly
   ```

---

## Keyboard Shortcuts

Press `?` inside the TUI at any time to show the built-in help overlay.

### Navigation

Dual-mode navigation — cursor keys and hjkl both work everywhere.

| Keys                    | Action                              |
|-------------------------|-------------------------------------|
| `Up` / `k`              | Move up                             |
| `Down` / `j`            | Move down                           |
| `Right` / `l`           | Expand group / open detail panel    |
| `Left` / `h`            | Collapse group                      |
| `Shift+Right` / `L`     | Focus detail panel                  |
| `Shift+Left` / `H`      | Focus back to list                  |

### Global

| Key       | Action                        |
|-----------|-------------------------------|
| `?`       | Show help overlay             |
| `q`       | Quit                          |
| `r`       | Force refresh all repos now   |
| `g`       | Toggle group view             |
| `s`       | Cycle sort order              |
| `/`       | Open fuzzy filter bar         |
| `Esc`     | Close detail / filter / modal |

Sort cycles through: **last run** → **status** → **alias**.

### On Selected Repo Row

| Key        | Action                                      |
|------------|---------------------------------------------|
| `Enter`    | Open build detail panel                     |
| `o`        | Open run in browser                         |
| `R`        | Re-run failed jobs for this build           |
| `Ctrl+R`   | Re-run entire workflow                      |
| `C`        | Clear cached detail for this repo           |
| `Ctrl+C`   | Clear all caches                            |

> `R` and `Ctrl+R` require `actions:write` PAT scope. ghastly warns gracefully
> if the scope is missing rather than showing a cryptic API error.

### In Detail Panel

| Key                 | Action                              |
|---------------------|-------------------------------------|
| `c`                 | Copy ref to clipboard               |
| `t`                 | Copy tag / version to clipboard     |
| `o`                 | Open run in browser                 |
| `Shift+Left` / `H`  | Focus back to list                  |
| `Esc`               | Close detail panel                  |

---

## Configuration

Config is stored at `~/.config/ghastly/config.toml`. After running
`ghastly init`, secure the file:

```sh
chmod 600 ~/.config/ghastly/config.toml
```

Full schema with all available options:

```toml
[auth]
pat = "ghp_xxxxxxxxxxxx"          # GitHub PAT — required

[display]
detail_layout = "auto"            # "auto" | "modal" | "split"
poll_interval = 30                # seconds between polls (default: 30)
theme = "textual-dark"            # Textual theme name

[notifications]
on_success = true
on_failure = true
on_cancelled = false
system_notify = true              # use notify-send for desktop notifications

log_level = "WARNING"             # Python log level: DEBUG | INFO | WARNING | ERROR

[[repos]]
url = "https://github.com/owner/repo"
alias = "my-service"              # display name (defaults to repo name)
group = "work"                    # used for group view (g key)
watch_branch = "main"             # only track runs on this branch; empty = default branch
artifact_hint = "auto"            # "auto" | "latest" | "releases"
```

### Configuration reference

#### `[auth]`

| Key   | Required | Description                  |
|-------|----------|------------------------------|
| `pat` | yes      | GitHub Personal Access Token |

#### `[display]`

| Key             | Default        | Description                                                             |
|-----------------|----------------|-------------------------------------------------------------------------|
| `detail_layout` | `"auto"`       | `"auto"` — split at ≥120 cols, otherwise modal; `"modal"`; `"split"`   |
| `poll_interval` | `30`           | Seconds between polling cycles                                          |
| `theme`         | `"textual-dark"` | Textual built-in theme name                                           |

#### `[notifications]`

| Key             | Default | Description                                       |
|-----------------|---------|---------------------------------------------------|
| `on_success`    | `true`  | Notify when a build transitions to success        |
| `on_failure`    | `true`  | Notify when a build transitions to failure        |
| `on_cancelled`  | `false` | Notify when a build is cancelled                  |
| `system_notify` | `true`  | Fire `notify-send` for desktop notifications      |

#### Top-level

| Key         | Default     | Description                                          |
|-------------|-------------|------------------------------------------------------|
| `log_level` | `"WARNING"` | File log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

#### `[[repos]]`

| Key             | Default    | Description                                                |
|-----------------|------------|------------------------------------------------------------|
| `url`           | required   | Full GitHub repository URL                                 |
| `alias`         | repo name  | Display name shown in the TUI                              |
| `group`         | `"default"`| Group label for the group view (`g` key)                   |
| `watch_branch`  | `""`       | Only show runs on this branch; empty = default branch      |
| `artifact_hint` | `"auto"`   | Controls how ghastly fetches artifact / version data       |

The `artifact_hint` option controls how ghastly fetches artifact data:

| Value      | Behaviour                                                         |
|------------|-------------------------------------------------------------------|
| `auto`     | Try `ghastly/v1` step summary first, then releases API fallback   |
| `latest`   | Skip all extraction — show run status only                        |
| `releases` | Use GitHub Releases API only, skip step summary parsing           |

---

## CLI Commands

All subcommands are available alongside the main TUI launcher.

| Command                              | Description                                      |
|--------------------------------------|--------------------------------------------------|
| `ghastly`                            | Launch the TUI dashboard                         |
| `ghastly init`                       | Interactive setup wizard                         |
| `ghastly add <url>`                  | Add a repository to the watch list               |
| `ghastly list`                       | List all watched repositories                    |
| `ghastly delete <id>`                | Remove a repository (index, URL, or owner/repo)  |
| `ghastly alias <id> <name>`          | Set a display alias for a repository             |
| `ghastly set-group <id> <group>`     | Move a repository into a group                   |
| `ghastly unset-group <id>`           | Reset a repository's group to `default`          |
| `ghastly status`                     | Print current build status of all repos          |
| `ghastly status --json`              | Machine-readable JSON output (see below)         |
| `ghastly clear-cache [repo]`         | Clear cached detail / hint data                  |

### `ghastly status`

Reads the persisted state file — no API call, instant output:

```sh
ghastly status
```

```
  ALIAS        STATUS    AGE       BRANCH  COMMIT
  ─────────────────────────────────────────────────────────
  api          success   2h 3m     main    Fix null reference in payment service
  frontend     failure   45m       main    Update button styles
  worker       running   0m        feat-x  Add retry logic

  2 passing  ·  1 failing  ·  1 running
```

With `--json`, the output is suitable for scripting and status-bar integrations:

```sh
ghastly status --json
```

```json
{
  "total": 3,
  "passing": 2,
  "failing": 1,
  "running": 0,
  "repos": [
    {
      "key": "owner/api",
      "alias": "api",
      "group": "default",
      "status": "success",
      "branch": "main",
      "commit": "Fix null reference in payment service",
      "updated_at": "2026-03-09T08:12:00+00:00",
      "url": "https://github.com/owner/api/actions/runs/123456789"
    }
  ]
}
```

#### Waybar integration example

```bash
# ~/.config/waybar/scripts/ghastly-status.sh
#!/usr/bin/env bash
ghastly status --json | jq -r '
  [
    (if .failing > 0 then "\(.failing) ✗" else empty end),
    (if .running > 0 then "\(.running) ⟳" else empty end),
    "\(.passing) ✓"
  ] | join("  ")
'
```

---

## Environment Variables

The PAT can be provided via environment variable instead of (or as a fallback
to) `~/.config/ghastly/config.toml`. ghastly checks in this order:

1. `[auth] pat` in `config.toml`
2. `GITHUB_TOKEN`
3. `GH_TOKEN`

This makes ghastly usable in shell sessions that already export the token
(e.g. via `gh auth` or CI-style tooling) without duplicating credentials.

---

## Workflow Integration

ghastly can parse a structured artifact manifest embedded in your workflow step
summaries, enabling richer display of what was built and at what version.

See [INTEGRATION.md](INTEGRATION.md) for copy-paste workflow snippets and the
full `ghastly/v1` schema reference.

---

## XDG Paths

| Path                                          | Purpose                                 |
|-----------------------------------------------|-----------------------------------------|
| `~/.config/ghastly/config.toml`               | Repos, PAT, preferences                 |
| `~/.local/share/ghastly/state.json`           | Last known run IDs for state diffing    |
| `~/.local/share/ghastly/etags.json`           | ETag cache for conditional HTTP requests|
| `~/.local/share/ghastly/detail_cache.json`    | Cached detail panel content per repo    |
| `~/.local/share/ghastly/manifest_hints.json`  | Cached `ghastly/v1` manifest hints      |
| `~/.local/share/ghastly/ghastly.log`          | Application log (level from config)     |

---

## Development Setup

```sh
git clone https://github.com/PLACEHOLDER_OWNER/ghastly
cd ghastly
uv sync
direnv allow
uv run ghastly init
```

Run the test suite:

```sh
uv run pytest tests/ -v
```

Run the linter:

```sh
uv run ruff check src/
uv run mypy
```

---

## Licence

ghastly is released under the [GNU General Public Licence v3.0](LICENSE).
