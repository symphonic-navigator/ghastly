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

### Navigation

Dual-mode navigation — cursor keys and hjkl both work everywhere.

| Keys         | Action                                 |
|--------------|----------------------------------------|
| `Up` / `k`   | Move up                                |
| `Down` / `j` | Move down                              |
| `Left` / `h` | Collapse group / close detail panel    |
| `Right` / `l`| Expand group / open detail panel       |

### Global

| Key       | Action                          |
|-----------|---------------------------------|
| `?`       | Show help overlay               |
| `q`       | Quit                            |
| `Shift+R` | Force refresh all repos now     |
| `g`       | Toggle group view               |
| `/`       | Open fuzzy filter bar           |
| `Esc`     | Close filter / detail / modal   |

### On Selected Repo Row

| Key       | Action                                              |
|-----------|-----------------------------------------------------|
| `Enter`   | Open build detail panel                             |
| `o`       | Open run in browser                                 |
| `r`       | Re-trigger failed steps only (`rerun-failed-jobs`)  |
| `Shift+R` | Re-trigger entire run (`rerun`)                     |
| `a`       | Add new repo (opens input prompt)                   |

> `r` and `Shift+R` require `actions:write` PAT scope. ghastly warns gracefully
> if the scope is missing rather than showing a cryptic API error.

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
poll_interval = 60                # seconds between polls

[notifications]
on_success = true
on_failure = true
on_cancelled = false
system_notify = true              # use notify-send for desktop notifications

[[repos]]
url = "https://github.com/owner/repo"
alias = "my-service"              # display name (defaults to repo name)
group = "work"                    # used for group view (g key)
watch_branch = "main"             # only track runs on this branch
artifact_hint = "auto"            # "auto" | "latest" | "releases"
```

The `artifact_hint` option controls how ghastly fetches artifact data:

| Value      | Behaviour                                                         |
|------------|-------------------------------------------------------------------|
| `auto`     | Try `ghastly/v1` step summary first, then releases API fallback   |
| `latest`   | Skip all extraction — show run status only                        |
| `releases` | Use GitHub Releases API only, skip step summary parsing           |

---

## Environment Variables

ghastly does not require any environment variables. The PAT and all
configuration live in `~/.config/ghastly/config.toml`.

---

## Workflow Integration

ghastly can parse a structured artifact manifest embedded in your workflow step
summaries, enabling richer display of what was built and at what version.

See [INTEGRATION.md](INTEGRATION.md) for copy-paste workflow snippets and the
full `ghastly/v1` schema reference.

---

## XDG Paths

| Path                                     | Purpose                            |
|------------------------------------------|------------------------------------|
| `~/.config/ghastly/config.toml`          | Repos, PAT, preferences            |
| `~/.local/share/ghastly/state.json`      | Last known run IDs for diffing     |
| `~/.local/share/ghastly/etags.json`      | ETag cache for conditional requests|
| `~/.local/share/ghastly/ghastly.log`     | Application log                    |

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
