# ghastly Workflow Integration

## Overview

`ghastly/v1` is a lightweight convention for embedding structured artifact
metadata into a GitHub Actions step summary. ghastly reads this data via the
GitHub API and surfaces it in the detail panel — showing exactly what was built,
at what version, and where it was published.

Without integration, ghastly still works: it falls back to the GitHub Releases
API for version information, and if that also yields nothing, it shows run
status and age only. Integration is opt-in and additive.

---

## Quickstart — Static Artifact List

For simple single-artifact workflows, add a final step that emits the manifest
as an HTML comment in `$GITHUB_STEP_SUMMARY`. GitHub does not render HTML
comments, so the block is invisible in the web UI but readable by ghastly.

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

The block must be written to `$GITHUB_STEP_SUMMARY` for ghastly to find it.
Append `>> $GITHUB_STEP_SUMMARY` to the `echo` commands if your workflow does
not set `$GITHUB_STEP_SUMMARY` as the default output target.

---

## Dynamic Artifacts — Accumulator Pattern

For workflows where the artifact list is determined at runtime (for example,
monorepos where only changed services are rebuilt), use an NDJSON accumulator
file. Each build step appends one JSON line; the final summary step reads all
lines and assembles the manifest.

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

The `if: always()` condition ensures the summary step runs even when earlier
build steps fail, giving ghastly partial artifact data for failed runs.

---

## Monorepo Pattern

In a monorepo where a single workflow run builds N services, each service's
build step appends one line to `$GHASTLY_ARTIFACTS_FILE`. The final summary
step reads all lines and emits a single `ghastly/v1` block containing all N
artifacts.

ghastly then displays all N artifacts in the detail panel for that single run
row. This is particularly useful when a shared library change triggers a cascade
rebuild of all dependent services — the dashboard shows every rebuilt component
at a glance without navigating to individual workflow runs.

Services that were not rebuilt in a given run are simply absent from that run's
artifact list. ghastly shows the most recent manifest it has seen, so the last
known version of an unmodified service remains visible in the detail panel.

---

## `ghastly/v1` Schema Reference

The artifact block must be a valid JSON object wrapped in an HTML comment using
the exact marker `<!-- ghastly:artifacts ... -->`.

| Field               | Type       | Required | Notes                                          |
|---------------------|------------|----------|------------------------------------------------|
| `schema`            | string     | Yes      | Must be exactly `"ghastly/v1"`                 |
| `built_at`          | ISO 8601   | Yes      | Build timestamp, e.g. `"2024-03-08T14:30:00Z"` |
| `trigger`           | string     | Yes      | GitHub event name: `push`, `workflow_dispatch`, etc. |
| `artifacts`         | array      | Yes      | List of produced artifacts; may be empty       |
| `artifacts[].name`  | string     | Yes      | Human-readable name of the artifact            |
| `artifacts[].type`  | string     | Yes      | One of: `docker`, `nuget`, `npm`, `binary`     |
| `artifacts[].version` | string   | Yes      | Version string, e.g. `"2.3.1-pre.847"`         |
| `artifacts[].ref`   | string     | Yes      | Full registry reference or feed URL            |

The schema is versioned. A future `ghastly/v2` will be non-breaking for tooling
that only knows `v1` — parsers that encounter an unknown schema version log a
warning and fall back gracefully.

---

## No Integration Needed

Repos without a ghastly summary step work fine. ghastly applies the following
fallback chain:

1. Parse `ghastly/v1` block from step summary (requires integration)
2. Fetch latest release tag from the GitHub Releases API
3. Show run conclusion and age only — no artifact data, no error state

The fallback is controlled by the `artifact_hint` option in `config.toml`:

| Value      | Behaviour                                                            |
|------------|----------------------------------------------------------------------|
| `auto`     | Try `ghastly/v1` first, then releases API, then status-only display  |
| `latest`   | Skip all artifact extraction — show run status only                  |
| `releases` | Use GitHub Releases API only, skip step summary parsing              |

Set `artifact_hint = "latest"` for repositories where extraction is noisy or
the releases API returns unrelated tags.
