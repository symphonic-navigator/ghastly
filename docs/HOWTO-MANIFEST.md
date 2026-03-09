# How to add a ghastly manifest to a GitHub Actions workflow

ghastly can display build details (image name, version, trigger) in its detail
panel when a workflow uploads a **ghastly/v1 manifest** as a GitHub Actions
artifact.

---

## How it works

1. Your workflow writes the manifest JSON to a file and uploads it as an
   artifact named `ghastly-manifest` using `actions/upload-artifact`.
2. When you press `Enter` on a repo row, ghastly calls the artifacts API,
   downloads the ZIP, extracts the JSON, and renders the artifact table in the
   detail panel.

> **Why not `$GITHUB_STEP_SUMMARY`?**
> GitHub Actions step summaries are NOT exposed via the check-runs API
> (`output.summary` is always `null` for native Actions jobs).  The artifacts
> API is the reliable, public way to attach structured data to a run.

---

## Requirements

### GitHub PAT scope

The PAT configured in `~/.config/ghastly/config.toml` must be able to read
Actions artifacts:

| PAT type       | Required scope / permission |
|----------------|-----------------------------|
| Classic PAT    | `repo`                      |
| Fine-grained   | `Actions: Read`             |

---

## Manifest format — `ghastly/v1`

The manifest is a plain JSON file:

```json
{
  "schema": "ghastly/v1",
  "built_at": "2025-01-01T12:00:00Z",
  "trigger": "push",
  "artifacts": [
    {
      "name":    "my-image",
      "type":    "docker",
      "version": "abc1234",
      "ref":     "ghcr.io/my-org/my-image:abc1234"
    }
  ]
}
```

All fields are strings.  `artifacts` is a list — include as many entries as the
job produces.  Extra fields are ignored; missing fields default to an empty
string.

---

## Workflow step template

Add the following two steps at the **end** of each job that produces artefacts.
Adjust the image name, type, and ref to match what the job actually builds.

```yaml
- name: Write ghastly manifest
  env:
    TRIGGER: ${{ github.event_name }}
    REF_TYPE: ${{ github.ref_type }}
    REF_NAME: ${{ github.ref_name }}
    REPO_OWNER: ${{ github.repository_owner }}
  run: |
    if [[ "$REF_TYPE" == "tag" ]]; then
      VERSION="$REF_NAME"
    else
      VERSION=$(echo "$GITHUB_SHA" | cut -c1-7)
    fi
    cat > ghastly-manifest.json << EOF
    {
      "schema": "ghastly/v1",
      "built_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
      "trigger": "$TRIGGER",
      "artifacts": [
        {
          "name": "my-image",
          "type": "docker",
          "version": "$VERSION",
          "ref": "ghcr.io/$REPO_OWNER/my-image:$VERSION"
        }
      ]
    }
    EOF
    # Optional: also write a human-readable summary for the GitHub Actions UI
    cat >> "$GITHUB_STEP_SUMMARY" << EOF
    ## Build complete

    | Field   | Value        |
    |---------|--------------|
    | Image   | my-image     |
    | Version | \`$VERSION\` |
    | Trigger | $TRIGGER     |
    EOF

- name: Upload ghastly manifest
  uses: actions/upload-artifact@v4
  with:
    name: ghastly-manifest-my-image   # must start with "ghastly-manifest"
    path: ghastly-manifest.json
    retention-days: 7
```

> **Version strategy used above:**
> Tag pushes (`v1.2.3`) use the tag name as the version.
> Branch pushes use the first 7 characters of the commit SHA.
> Adjust to whatever versioning scheme the project uses.

---

## Multiple artefacts in one job

List them all in the `artifacts` array:

```json
"artifacts": [
  {
    "name": "my-api",
    "type": "docker",
    "version": "abc1234",
    "ref": "ghcr.io/my-org/my-api:abc1234"
  },
  {
    "name": "my-frontend",
    "type": "docker",
    "version": "abc1234",
    "ref": "ghcr.io/my-org/my-frontend:abc1234"
  }
]
```

---

## Jobs that split work across multiple jobs

If the workflow has separate jobs (e.g. `build-api` and `build-frontend`), add
the two manifest steps to **each job independently**.  Since artifact names must
be unique per run, give each one a distinct suffix — ghastly matches any artifact
whose name **starts with** `ghastly-manifest`:

```yaml
# in build-api job
name: ghastly-manifest-api

# in build-frontend job
name: ghastly-manifest-frontend
```

ghastly reads the first matching artifact it finds.

If you need both jobs' data visible in ghastly, consolidate the artifacts into
a single manifest (e.g. in a final summary job that depends on both build jobs).

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| "No summary available" | Artifact not uploaded — confirm the `Upload ghastly manifest` step ran and succeeded. |
| Artifact table shows but fields are empty | Field names in the JSON do not match the schema (`name`, `type`, `version`, `ref`). |
| "Unsupported ghastly schema version" in log | `"schema"` field is missing or not exactly `"ghastly/v1"`. |
| Artifact found but not parsed | The JSON is malformed — check the `Write ghastly manifest` step output on GitHub. |

Logs are written to `~/.local/share/ghastly/ghastly.log`.  Set
`log_level = "DEBUG"` in `~/.config/ghastly/config.toml` for verbose output
while diagnosing.
