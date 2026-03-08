# ghastly — Build Playbook
> Step-by-step guide for building ghastly from zero to PyPI 👻
> Hand this to Claude Code. It has everything it needs.

---

## How to use this playbook

Each phase has a goal, a task list, and acceptance criteria.
**A phase is done when all acceptance criteria pass — not before.**
Phases build on each other; don't skip ahead.

The companion document `ghastly-brief.md` is the source of truth for all
design decisions, schemas, keybinds, and UX behavior. When in doubt, brief wins.

---

## Phase 1 — Walking Skeleton

**Goal:** A real running TUI that polls one repo and shows green or red.
Nothing fancy. Just proof it works end to end.

### Tasks

- [ ] Init project with `uv init`, `direnv`, `.venv`, `pyproject.toml`
- [ ] Set up `src/ghastly/` package structure (all files as stubs)
- [ ] Implement `ghastly init` wizard
  - prompt for PAT
  - validate PAT via `GET /user` (checks auth + returns login)
  - prompt for first repo URL
  - write `~/.config/ghastly/config.toml`
  - create `~/.local/share/ghastly/` directory
- [ ] Implement `config.py` — load and validate config.toml
- [ ] Implement `api.py` — single method: `get_latest_run(owner, repo)` via
  `GET /repos/{owner}/{repo}/actions/runs?per_page=1`
- [ ] Implement minimal Textual app in `app.py`
  - static list of repo rows from config
  - each row shows: alias · status (colored) · last updated timestamp
  - polling loop at configured interval (default 60s)
- [ ] Implement `repo_row.py` widget — bare minimum, status + alias only
- [ ] `ghastly add <url>` CLI command appends repo to config

### Acceptance Criteria

- `ghastly init` runs cleanly, writes valid config, exits with helpful message
- `ghastly` launches and shows a row per configured repo
- Status updates after each poll cycle
- `success` rows are green, `failure` rows are red, `in_progress` is yellow
- `q` quits cleanly
- App does not crash if GitHub returns an unexpected status code

### Key decisions for this phase

- Use `typer` for CLI commands (`init`, `add`) alongside the TUI entry point
- PAT stored as plaintext in config.toml — document that users should `chmod 600` it
- Polling is a simple `asyncio` loop with `await asyncio.sleep(interval)`

---

## Phase 2 — Core Loop

**Goal:** The daily driver experience. Notifications, age column, state
diffing, ETag support. This is the phase where ghastly becomes genuinely useful.

### Tasks

- [ ] Add **age column** to repo rows
  - format: `build completed  01:00:25 ago` / `build failed  00:25:33 ago`
  - live update every second via Textual timer
  - color-matched to last status (green/red)
- [ ] Implement **state diffing** in `api.py`
  - persist last known run ID per repo to `~/.local/share/ghastly/state.json`
  - detect transitions: any status → `success`, any status → `failure`, etc.
  - only fire notifications on actual change, not every poll
- [ ] Implement **ETag caching**
  - send `If-None-Match` header with stored ETag on every request
  - on `304 Not Modified`: skip update, no rate limit cost
  - persist ETags to `~/.local/share/ghastly/etags.json`
- [ ] Implement `notifications.py`
  - TUI toast via Textual `notify()`
  - system notification via `notify-send` (subprocess, optional)
  - configurable per event type via `[notifications]` config section
- [ ] Add **row highlight animation** on status change (Textual CSS transition)
- [ ] Add **status bar** at bottom of app
  - shows: last poll time · next poll in Xs · repo count · rate limit remaining
  - shows `[offline]` if last request failed with network error
  - shows rate limit reset time if 403/429 received
- [ ] Implement **config file watching** via `watchfiles`
  - new repos added to config appear in TUI without restart
  - removed repos disappear gracefully

### Acceptance Criteria

- Age column updates live every second without UI flicker
- Notification fires exactly once per state transition, not on every poll
- ETag requests return 304 for unchanged repos — verify via debug log
- `notify-send` fires on failure if `system_notify = true`
- Status bar shows accurate rate limit info
- Adding a repo via `ghastly add` while TUI is running adds the row live
- App recovers gracefully after network outage (resumes polling, shows [offline])

### Key decisions for this phase

- Age formatted as `HH:MM:SS` — switch to `Xd HH:MM` for runs older than 24h
- Persist state/etags as JSON, not SQLite — keeps it simple and inspectable
- `notify-send` failure (e.g. not installed) should log a warning, never crash

---

## Phase 3 — Artifact Extraction

**Goal:** Show what was built. The `ghastly/v1` schema, releases fallback,
and the detail panel. This is the feature that makes cor.energy colleagues
want it too.

### Tasks

- [ ] Implement `schema.py` — `ghastly/v1` extractor
  - fetch step summary via `GET /repos/{owner}/{repo}/actions/runs/{run_id}`
    then `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs` for summary URL
  - regex extract `<!-- ghastly:artifacts ... -->` block
  - parse and validate JSON against schema
  - return typed `ArtifactManifest` dataclass
- [ ] Implement **releases API fallback**
  - `GET /repos/{owner}/{repo}/releases/latest`
  - extract tag name as version, build minimal artifact list
  - only used when `ghastly/v1` block not found
- [ ] Add **artifacts column** to repo rows
  - show artifact count if `ghastly/v1` found: `3 artifacts`
  - show latest release tag if releases fallback: `v2.3.1`
  - show `—` if no artifact data available
- [ ] Implement `detail_panel.py` widget
  - renders full Step Summary markdown (Textual `Markdown` widget)
  - shows `ghastly/v1` artifact table above markdown if available:
    ```
    name              type     version          ref
    heating-service   docker   2.3.1-pre.847    ghcr.io/...
    common-lib        nuget    1.0.4-pre.847    https://...
    ```
  - falls back to log tail snippet if no summary available
- [ ] Wire `Enter` key to open detail panel
- [ ] Wire `o` key to open `html_url` in browser (`webbrowser.open()`)

### Acceptance Criteria

- `ghastly/v1` block correctly parsed from a real workflow step summary
- Artifact table renders correctly for docker + nuget types
- Releases fallback works for a public repo with releases
- `—` shown cleanly for repos with no artifact data (no error, no empty box)
- `Enter` opens detail panel, `Esc` closes it
- `o` opens correct GitHub run URL in default browser
- Schema version mismatch (`ghastly/v2` on a v1 parser) logs warning, shows raw JSON

### Key decisions for this phase

- Step summary fetching adds 1 extra API call per run — only fetch on detail
  open, not during polling, to preserve rate limit budget
- `artifact_hint = "latest"` in config skips all extraction attempts, shows
  run status only — escape hatch for repos where extraction is noisy

---

## Phase 4 — UX Polish

**Goal:** The experience that makes people switch from their browser.
Adaptive layout, full navigation, fuzzy filter, group view, rerun support.

### Tasks

- [ ] Implement **adaptive layout**
  - detect terminal width on launch and on resize (`on_resize` in Textual)
  - `< 120 cols`: detail opens as modal overlay
  - `≥ 120 cols`: detail opens as right-side split panel
  - respect `[display] detail_layout` config override
- [ ] Implement **full keyboard navigation**
  - `↑`/`k` and `↓`/`j` move between rows
  - `←`/`h` collapses group or closes detail panel
  - `→`/`l` expands group or opens detail panel
  - all navigation works identically in both modal and split modes
- [ ] Implement **group view**
  - `g` toggles between flat list and grouped-by-`group` view
  - groups are collapsible with `h`/`l`
  - group header shows aggregate status (worst status of members)
- [ ] Implement **fuzzy filter bar** (`filter_bar.py`)
  - `/` opens filter input at bottom of screen
  - live filtering as user types — no enter required
  - matches against: alias, group name, status string, artifact name
  - fuzzy: `hea` matches `heating-service`, `wrk` matches `work`
  - `Esc` clears filter and closes bar
  - matched substring highlighted in row
- [ ] Implement **`?` help overlay**
  - full keybind reference rendered as Textual overlay
  - dismissable with `?` or `Esc`
- [ ] Implement **rerun support** (requires `actions:write` PAT scope)
  - `r` → `POST /repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs`
  - `Shift+R` → `POST /repos/{owner}/{repo}/actions/runs/{run_id}/rerun`
  - show confirmation prompt before firing
  - if PAT lacks `actions:write`: show inline warning message, don't crash
- [ ] Sort options — cycle with `s` key: last run time · status · alias
- [ ] Add **duration column** — how long the last run took (from API `run_started_at` + `updated_at`)

### Acceptance Criteria

- At 100 cols: detail opens as modal, `Esc` dismisses
- At 140 cols: detail opens as split panel, `Esc` collapses it
- Resizing terminal mid-session switches layout correctly
- `hjkl` and arrow keys both navigate rows without any config
- `/hea` + typing filters to heating-service live, match highlighted
- `Esc` from filter restores full list instantly
- Group view shows aggregate status in group header
- `r` rerun fires only after confirmation, shows toast on success
- `r` with read-only PAT shows warning, does NOT attempt the API call
- `?` overlay shows all keybinds, closes cleanly

### Key decisions for this phase

- Fuzzy matching: implement simple substring score (no external dep like `fzf`).
  Score = position of match (earlier = better) + consecutive match bonus.
  `rapidfuzz` is acceptable if simple scoring feels insufficient.
- Confirmation prompt for rerun: single keypress `y`/`n`, not a modal dialog

---

## Phase 5 — Distribution

**Goal:** Anyone can install ghastly in 30 seconds. PyPI, AUR, docs.

### Tasks

- [ ] Finalize `pyproject.toml`
  - entry points: `ghastly` CLI + TUI
  - all dependencies pinned with lower bounds
  - metadata: description, license (GPLv3), homepage, keywords
- [ ] Write `README.md`
  - install instructions (pip, uv, AUR)
  - quickstart: init → add repo → launch
  - screenshot (record with `vhs` or similar)
  - link to `INTEGRATION.md`
- [ ] Write `INTEGRATION.md`
  - quickstart workflow snippet (static)
  - accumulator pattern (dynamic / monorepo)
  - `ghastly/v1` schema reference table
  - "no integration needed" section
- [ ] Write `PKGBUILD` for AUR
  - source from PyPI tarball
  - `depends = ('python' 'python-pip')`
  - install to standard Arch paths
  - include `.install` file with post-install note about `ghastly init`
- [ ] Write **systemd user service** snippet for docs
  ```ini
  [Unit]
  Description=ghastly GitHub Actions watcher

  [Service]
  ExecStart=%h/.local/bin/ghastly
  Restart=on-failure

  [Install]
  WantedBy=default.target
  ```
- [ ] Publish to PyPI via `uv publish` / `hatch publish`
- [ ] Submit AUR package

### Acceptance Criteria

- `pip install ghastly` works on a clean Python 3.11+ environment
- `uv tool install ghastly` works
- AUR: `yay -S ghastly` installs and runs correctly on Arch
- README screenshot shows real running TUI
- `INTEGRATION.md` copy-paste workflow snippet produces valid `ghastly/v1` JSON
- systemd service starts ghastly and restarts it on crash

---

## Cross-cutting Concerns

These apply to every phase, not just one.

### Error handling philosophy
- Never crash on a single repo's API failure — log it, mark the row, continue
- Never show raw Python tracebacks to the user — catch at app boundary
- Always preserve last known state when API is unavailable

### Logging
- Use Python `logging` module, not print statements
- Log file: `~/.local/share/ghastly/ghastly.log`
- Default level: `WARNING`. Set `log_level = "DEBUG"` in config for verbose mode
- Debug mode logs every API request + response code (useful for ETag verification)

### Testing
- Unit tests for `schema.py` extractor — test valid JSON, missing block, malformed JSON, version mismatch
- Unit tests for `config.py` — test missing file, invalid TOML, missing required fields
- Integration tests for `api.py` — use `respx` to mock `httpx` calls
- No tests required for Textual widgets in early phases — they're hard to test and the framework is visual

### Code style
- All comments, docstrings, and variable names in English
- Type hints everywhere — `mypy --strict` should pass
- `ruff` for formatting and linting

---

## Reference — Key API Endpoints

| purpose | endpoint |
|---|---|
| validate PAT | `GET /user` |
| latest run for repo | `GET /repos/{owner}/{repo}/actions/runs?per_page=1&branch={branch}` |
| run detail (for html_url) | `GET /repos/{owner}/{repo}/actions/runs/{run_id}` |
| step summary | `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs` → job `steps[].summary_url` |
| latest release | `GET /repos/{owner}/{repo}/releases/latest` |
| rerun failed jobs | `POST /repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs` |
| rerun all | `POST /repos/{owner}/{repo}/actions/runs/{run_id}/rerun` |

All requests use `Authorization: Bearer {PAT}` header.
All GET requests send `If-None-Match: {etag}` when a cached ETag exists.

---

## Reference — Config Schema

```toml
[auth]
pat = "ghp_xxxxxxxxxxxx"

[display]
detail_layout = "auto"   # "auto" | "modal" | "split"
poll_interval = 60       # seconds

[notifications]
on_success = true
on_failure = true
on_cancelled = false
system_notify = true

[[repos]]
url = "https://github.com/owner/repo"
alias = "my-service"
group = "work"
watch_branch = "main"
artifact_hint = "auto"   # "auto" | "latest" | "releases"
```

---

*ghastly — because watching CI in a browser tab is haunting you* 👻
