# ghastly — feature ideas backlog

Ideas collected after reviewing the full codebase. Ordered roughly by impact/effort ratio.

---

## Tier 1 — small change, high value

### ✅ `GITHUB_TOKEN` / `GH_TOKEN` env-var fallback
If `pat` is absent or empty in config, fall back to `$GITHUB_TOKEN` or `$GH_TOKEN`.
Standard practice; makes ghastly work without touching config in CI or shell sessions
that already export the token.

### ✅ Build duration column in `RepoRow`
`RunData` already carries `run_started_at` and `updated_at`.
- Completed runs: `updated_at − run_started_at` → static duration
- In-progress runs: `now − run_started_at` → live elapsed timer (updates every tick)

Format: `m:ss` / `h:mm:ss`.  Makes slow or stuck builds immediately visible.

### ✅ `ghastly status` CLI command (with `--json`)
Reads `state.json` — no API call, instant.
Default: aligned table with alias, status, branch, commit.
`--json`: machine-readable output with `total / passing / failing / running` summary +
per-repo array. Perfect for Waybar custom modules, shell scripts, dashboards.

### Jump to next failing (`n` / `N`)
Keyboard shortcut that moves focus to the next/previous repo with `failure` status.
Especially useful when monitoring many repos.  Implementation: iterate visible
`RepoRow` widgets in `app.py`, wrap around.

---

## Tier 2 — medium effort, clearly useful

### Workflow filter per repo (`watch_workflow`)
New `watch_workflow = "Deploy"` field in `[[repos]]`.
The `/actions/runs` API supports `?workflow_id=` and filtering by name.
Lets you watch a specific workflow (e.g. Deploy) rather than whatever ran last.

### Mute/unmute notifications per repo (in-TUI)
Press `m` on a focused row to toggle notifications for that repo.
State persisted in `state.json`.  Practical during active debugging — suppresses
noise without editing config.

### Per-repo poll interval override
Optional `poll_interval = 10` in `[[repos]]` overrides the global value.
Useful for repos under active development.

### Stuck-build detection / timeout warning
`timeout_minutes = 30` globally or per repo.
If a run stays `in_progress` longer than the threshold, show a visual warning
(different colour or `!` marker in the row).  Practical for catching hung jobs.

---

## Tier 3 — larger change, high value

### Run history in detail panel
Second API call on `/actions/runs?per_page=5` when the detail panel opens.
Show a mini table: date, duration, status, commit.  Instantly reveals whether a
failure is a flaky one-off or a persistent regression.

### Multiple workflows per repo (sub-rows)
`watch_workflows = ["CI", "Deploy"]` as a list in `[[repos]]`.
Each workflow gets its own sub-row under a repo header.
Requires a significant refactor of the polling loop and `RepoRow` composition,
but very powerful for monorepos or repos with separate CI/deploy pipelines.

### Step-level detail for in-progress builds
Show individual job steps and their status inside the detail panel while a run
is active.  Requires polling the jobs endpoint periodically.

### Workflow dispatch trigger from TUI
Press `D` on a row to trigger a `workflow_dispatch` run for repos that support it.
Needs an input dialog for optional inputs.
API: `POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches`.

### PR context in row / detail panel
When a run was triggered by a pull request, surface the PR number and title.
The raw run response already contains a `pull_requests` array — just needs parsing
into `RunData` and display in the row or detail panel.

---

## Bonus: Waybar integration snippet

```bash
# ~/.config/waybar/scripts/ghastly-status.sh
ghastly status --json | jq -r '
  (.failing | if . > 0 then "\(.) ✗" else empty end),
  (.running | if . > 0 then "\(.) ⟳" else empty end),
  (.passing | tostring) + " ✓"
  | @tsv
' | paste -sd ' '
```
