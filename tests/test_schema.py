"""Unit tests for ghastly.schema — ghastly/v1 manifest extraction."""

from __future__ import annotations

import textwrap

import pytest

from ghastly.schema import ArtifactManifest, extract_manifest


def _wrap(json_body: str) -> str:
    """Wrap a JSON body in the ghastly:artifacts HTML comment."""
    return f"<!-- ghastly:artifacts\n{json_body}\n-->"


VALID_JSON = textwrap.dedent("""\
    {
        "schema": "ghastly/v1",
        "built_at": "2024-03-08T12:00:00Z",
        "trigger": "push",
        "artifacts": [
            {
                "name": "heating-service",
                "type": "docker",
                "version": "2.3.1-pre.847",
                "ref": "ghcr.io/org/heating-service:2.3.1-pre.847"
            }
        ]
    }
""")


def test_valid_manifest() -> None:
    """Full valid ghastly/v1 block parses to a populated ArtifactManifest."""
    result = extract_manifest(_wrap(VALID_JSON))

    assert isinstance(result, ArtifactManifest)
    assert result.schema == "ghastly/v1"
    assert result.trigger == "push"
    assert result.built_at is not None
    assert result.built_at.year == 2024

    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.name == "heating-service"
    assert artifact.type == "docker"
    assert artifact.version == "2.3.1-pre.847"
    assert artifact.ref == "ghcr.io/org/heating-service:2.3.1-pre.847"


def test_missing_block() -> None:
    """Plain markdown with no ghastly comment returns None."""
    result = extract_manifest("## Build complete\n\nAll steps passed.")
    assert result is None


def test_malformed_json() -> None:
    """A ghastly comment containing broken JSON returns None without raising."""
    malformed = "<!-- ghastly:artifacts\n{ this is not : valid json\n-->"
    result = extract_manifest(malformed)
    assert result is None


def test_wrong_version() -> None:
    """A ghastly/v2 block returns None and does not raise."""
    v2_json = textwrap.dedent("""\
        {
            "schema": "ghastly/v2",
            "built_at": "2024-03-08T12:00:00Z",
            "trigger": "push",
            "artifacts": []
        }
    """)
    result = extract_manifest(_wrap(v2_json))
    assert result is None


def test_empty_artifacts() -> None:
    """A valid block with an empty artifacts list parses successfully."""
    empty_json = textwrap.dedent("""\
        {
            "schema": "ghastly/v1",
            "built_at": "2024-03-08T12:00:00Z",
            "trigger": "workflow_dispatch",
            "artifacts": []
        }
    """)
    result = extract_manifest(_wrap(empty_json))

    assert isinstance(result, ArtifactManifest)
    assert result.artifacts == []
    assert result.trigger == "workflow_dispatch"


def test_missing_required_field() -> None:
    """A JSON object missing the 'schema' field returns None."""
    no_schema_json = textwrap.dedent("""\
        {
            "built_at": "2024-03-08T12:00:00Z",
            "trigger": "push",
            "artifacts": []
        }
    """)
    # schema field defaults to "" which does not match "ghastly/v1"
    result = extract_manifest(_wrap(no_schema_json))
    assert result is None
