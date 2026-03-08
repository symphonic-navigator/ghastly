# ghastly — Project Brief
> GitHub ActionS waTcher · Terminal-native build monitor 👻

## What is it?

A Textual-based TUI dashboard for monitoring GitHub Actions across multiple
repositories. Designed for developers running parallel build sessions (e.g.
multiple Claude Code instances) who need ambient awareness of build status and
artifact versions — without switching context.

Terminal-native, keyboard-first, Arch-demographic. Released under GPLv3.

---

## Core Use Case

1. Claude Code (or any CI trigger) kicks off a build
2. ghastly detects the state change and notifies — even when you're not looking
3. On completion, artifact versions are immediately visible in the dashboard

---

## Core Features

### Auth
- GitHub Personal Access Token (PAT) with `repo` + `actions:read` scope
- Optional `actions:write` scope for run re-trigger support
- Stored in `~/.config/ghastly/config.toml`
- No OAuth needed — personal tool

### Repo Management
- Add repos via standard web URL: `https://github.com/owner/repo`
- Parser extracts `owner` + `repo` for API calls
- Persisted in config file
- `ghastly add <url>` CLI command — no manual TOML editing required
- `ghastly init` — interactive setup wizard: PAT input, validation, first repo
- Config file is watched at runtime — additions picked up without restart

### Repo Config Options

```toml
[[repos]]
url = "https://github.com/cor-energy/heating-service"
alias = "heating"
group = "work"
watch_branch = "main"
artifact_hint = "auto"   # "auto" | "latest" | "releases"
```

### Status Display (one row per repo)

Columns: `alias` · `branch` · `status` · `duration` · `artifacts` · `age`

**Status values with color:**

| status | color | meaning |
|---|---|---|
| `queued` | dim white | waiting to run |
| `in_progress` | yellow | currently running |
| `success` | **green** | completed successfully |
| `failure` | **red** | build failed |
| `cancelled` | dim red | manually cancelled |

**Age column** — time since last run completed:
```
build completed  01:00:25 ago
build failed     00:25:33 ago
```

Format: `HH:MM:SS ago` updating live, color-matched to status (green/red).

Polling via `GET /repos/{owner}/{repo}/actions/runs?per_page=1`
Poll interval: configurable, default `60s`
ETag / `If-None-Match` conditional requests to stay within rate limits.

### Grouping & Filtering

- Repos organized by `group` field in config
- `g` — toggle group view
- `/` — fuzzy filter bar (matches against alias, group, status, artifact name)
  - fuzzy matching via substring score — `hea` matches `heating-service`
  - filter is live as you type, `Esc` to clear
- Sort by: last run time, status, alias (configurable)

---

## Build Detail View

### Adaptive Layout

ghastly adapts the detail view to terminal width automatically:

| terminal width | layout |
|---|---|
| `< 120 cols` | modal overlay (full-screen, dismissable) |
| `≥ 120 cols` | vertical split — repo list left, detail right |

Override via config:
```toml
[display]
detail_layout = "auto"   # "auto" | "modal" | "split"
```

### Detail Panel Contents
- Full Step Summary markdown rendered
- `ghastly/v1` artifact table if available (name · type · version · ref)
- Raw log tail as fallback
- `o` to open the run in browser (`html_url` from API response — available directly, no scraping)

---

## Keyboard Shortcuts

### Navigation

Dual-mode navigation — cursor keys and hjkl both work everywhere, always.
No mode switching, no configuration needed. Vim refugees welcome.

| keys | action |
|---|---|
| `↑` / `k` | move up |
| `↓` / `j` | move down |
| `←` / `h` | collapse group / close detail panel |
| `→` / `l` | expand group / open detail panel |

### Global

| key | action |
|---|---|
| `?` | show help overlay |
| `q` | quit |
| `Shift+R` | force refresh all repos now |
| `g` | toggle group view |
| `/` | open fuzzy filter bar |
| `Esc` | close filter / detail / modal |

### On selected repo row

| key | action |
|---|---|
| `Enter` | open build detail panel |
| `o` | open run in browser |
| `r` | re-trigger failed steps only (`POST .../rerun-failed-jobs`) |
| `Shift+R` | re-trigger entire run (`POST .../rerun`) |
| `a` | add new repo (opens input prompt) |

> `r` and `Shift+R` require `actions:write` PAT scope. ghastly warns gracefully
> if scope is missing rather than showing a cryptic API error.

---

## Artifact Extraction — `ghastly/v1` Schema

ghastly uses a **convention-based extraction pipeline**, checked in order:

### 1. `ghastly/v1` embedded JSON (primary, richest)

The last step of a workflow emits a structured JSON block embedded in the
GitHub Step Summary as an HTML comment. GitHub doesn't render it; ghastly
finds and parses it via regex `<!-- ghastly:artifacts\s*([\s\S]*?)-->`.

**Schema — `ghastly/v1`:**

| field | type | required | notes |
|---|---|---|---|
| `schema` | string | ✅ | always `"ghastly/v1"` |
| `built_at` | ISO 8601 | ✅ | build timestamp |
| `trigger` | string | ✅ | `push`, `workflow_dispatch`, etc. |
| `artifacts` | array | ✅ | list of produced artifacts |
| `artifacts[].name` | string | ✅ | human name |
| `artifacts[].type` | string | ✅ | `docker` \| `nuget` \| `npm` \| `binary` |
| `artifacts[].version` | string | ✅ | semver, e.g. `2.3.1-pre.847` |
| `artifacts[].ref` | string | ✅ | full registry ref or feed URL |

Schema is versioned — future `ghastly/v2` additions are non-breaking.

### 2. GitHub Releases API (fallback)

`GET /repos/{owner}/{repo}/releases/latest` — semver tag available directly.
Used when no `ghastly/v1` block is found in step summary.

### 3. Graceful degradation (final fallback)

Show run conclusion + age only. No artifact data, no error state.
Triggered by `artifact_hint = "latest"` or when releases API returns nothing.

---

## Workflow Integration

### Quickstart — static artifact list

For simple single-artifact workflows, hardcode the summary step:

```yaml
- name: ghastly summary
  if: always()
  run: |
    echo "<!-- ghastly:artifacts"
    echo '{
      "schema": "ghastly/v1",
      "built_at": "${{ github.event.head_commit.timestamp }}",
      "trigger": "${{ github.event_name }}",
      "artifacts": [
        {
          "name": "my-service",
          "type": "docker",
          "version": "${{ env.VERSION }}",
          "ref": "ghcr.io/owner/my-service:${{ env.VERSION }}"
        }
      ]
    }'
    echo "-->"
```

### Dynamic artifacts — accumulator pattern

For workflows where the artifact list is determined at runtime (e.g. monorepos
where only changed services are rebuilt), use a temp file accumulator:

```yaml
env:
  GHASTLY_ARTIFACTS_FILE: /tmp/ghastly-artifacts.ndjson

jobs:
  build:
    steps:
      # Each build step appends its artifact JSON line to the accumulator file
      - name: build heating-service
        run: |
          VERSION=$(./scripts/get-version.sh heating-service)
          docker build -t ghcr.io/org/heating-service:$VERSION .
          echo "{\"name\":\"heating-service\",\"type\":\"docker\",\"version\":\"$VERSION\",\"ref\":\"ghcr.io/org/heating-service:$VERSION\"}" \
            >> $GHASTLY_ARTIFACTS_FILE

      # Final step assembles the full ghastly/v1 block
      - name: ghastly summary
        if: always()
        run: |
          ARTIFACTS=$(cat $GHASTLY_ARTIFACTS_FILE | jq -s '.')
          PAYLOAD=$(jq -n \
            --arg schema "ghastly/v1" \
            --arg built_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            --arg trigger "${{ github.event_name }}" \
            --argjson artifacts "$ARTIFACTS" \
            '{schema:$schema, built_at:$built_at, trigger:$trigger, artifacts:$artifacts}')
          echo "<!-- ghastly:artifacts"
          echo "$PAYLOAD"
          echo "-->"
          # also render human-readable table for GitHub UI
          echo "## Build Artifacts"
          echo "| name | type | version |"
          echo "|------|------|---------|"
          echo "$ARTIFACTS" | jq -r '.[] | "| \(.name) | \(.type) | \(.version) |"'
```

### Monorepo pattern

In a monorepo where a single workflow run builds N services, each service's
build step appends to `$GHASTLY_ARTIFACTS_FILE`. The final summary step sees
all of them. ghastly then displays all N artifacts in the detail panel for
that single run row — exactly matching the cor.energy use case where building
a shared library cascades into rebuilding all dependent services.

### No integration? No problem.

Repos without a ghastly summary step fall back to the releases API, then to
run status only. ghastly never errors on missing integration — it just shows
less data.

---

## Error States & UX

| condition | display |
|---|---|
| PAT missing / invalid | startup error with `ghastly init` prompt |
| PAT lacks `actions:write` | `r`/`R` keys show inline warning, don't crash |
| API rate limited | status bar shows rate limit reset time, polling pauses |
| Repo not found / renamed | row shows `⚠ not found` — doesn't block other repos |
| No network | last known state preserved, `[offline]` indicator in status bar |
| Step summary unavailable | falls back silently, no error shown to user |

---

## Live Notifications

- State diffing between polls — only fires on actual state *change*
- In-TUI: toast notification + row highlight animation
- System: `notify-send` desktop notification (optional, configurable)
- Configurable per event type:

```toml
[notifications]
on_success = true
on_failure = true
on_cancelled = false
system_notify = true   # notify-send
```

---

## Rate Limit Strategy

With PAT: 5000 req/h. At 60s intervals across 20 repos = ~1200 req/h — fine,
but ETag conditional requests (`If-None-Match`) are used from day one so 304
responses don't count against the limit. State (ETags + last run IDs) persisted
to `~/.local/share/ghastly/` across sessions.

---

## Tech Stack

| tool | purpose |
|---|---|
| `textual` | TUI framework |
| `httpx` | async HTTP client |
| `tomllib` | config parsing (stdlib, Python 3.11+) |
| `watchfiles` | live config reload |
| `uv` | package management |
| `direnv` + `.venv` | dev environment |

---

## Project Structure

```
ghastly/
├── src/ghastly/
│   ├── __init__.py
│   ├── app.py              # Textual app entry point
│   ├── api.py              # GitHub API client (httpx, ETag, rate limit)
│   ├── config.py           # Config loading + file watching
│   ├── schema.py           # ghastly/v1 JSON schema + extractor
│   ├── notifications.py    # notify-send + TUI toast bridge
│   └── widgets/
│       ├── repo_row.py     # Single repo status row
│       ├── detail_panel.py # Build detail + artifact view
│       └── filter_bar.py   # Live filter / group toggle
├── pyproject.toml
├── .envrc
├── LICENSE                 # GPLv3
└── README.md
```

---

## XDG Compliance

| path | purpose |
|---|---|
| `~/.config/ghastly/config.toml` | repos, PAT, preferences |
| `~/.local/share/ghastly/state.json` | last known run IDs for diffing |
| `~/.local/share/ghastly/etags.json` | ETag cache |

---

## Distribution

- **PyPI** via `uv` / `hatch`
- **AUR** package (`PKGBUILD`) — natural fit for Arch users
- Optional **systemd user service** snippet in docs for always-on dashboard use

---

## Name

**ghastly** — GitHub ActionS waTcher (+ haunted vibes 👻)
