"""ghastly/v1 schema extractor for step summary artifact manifests."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

_BLOCK_RE = re.compile(r"<!-- ghastly:artifacts\s*([\s\S]*?)-->", re.MULTILINE)

SUPPORTED_SCHEMA = "ghastly/v1"


@dataclass
class ArtifactItem:
    """A single artifact entry from the manifest."""

    name: str
    type: str
    version: str
    ref: str


@dataclass
class ArtifactManifest:
    """Parsed ghastly/v1 artifact manifest embedded in a step summary."""

    schema: str
    built_at: datetime | None
    trigger: str
    artifacts: list[ArtifactItem]


def extract_manifest(summary_text: str) -> ArtifactManifest | None:
    """Extract and parse an artifact manifest from a step summary string.

    Returns an ArtifactManifest if a valid ghastly/v1 block is found,
    or None on any failure (missing block, wrong schema, parse error, etc.).
    Never raises.
    """
    match = _BLOCK_RE.search(summary_text)
    if not match:
        return None

    raw_json = match.group(1).strip()
    try:
        data: object = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse ghastly artifact JSON: %s", exc)
        return None

    if not isinstance(data, dict):
        logger.warning("ghastly artifact block is not a JSON object")
        return None

    schema = data.get("schema", "")
    if schema != SUPPORTED_SCHEMA:
        logger.warning(
            "Unsupported ghastly schema version %r — expected %r; ignoring manifest",
            schema,
            SUPPORTED_SCHEMA,
        )
        return None

    built_at: datetime | None = None
    raw_built_at = data.get("built_at")
    if isinstance(raw_built_at, str):
        try:
            built_at = datetime.fromisoformat(raw_built_at.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Cannot parse built_at %r in ghastly manifest", raw_built_at)

    trigger = str(data.get("trigger", ""))

    artifacts: list[ArtifactItem] = []
    raw_artifacts = data.get("artifacts", [])
    if not isinstance(raw_artifacts, list):
        logger.warning("ghastly manifest 'artifacts' is not a list")
        return None

    for entry in raw_artifacts:
        if not isinstance(entry, dict):
            logger.warning("Skipping non-object artifact entry: %r", entry)
            continue
        artifacts.append(
            ArtifactItem(
                name=str(entry.get("name", "")),
                type=str(entry.get("type", "")),
                version=str(entry.get("version", "")),
                ref=str(entry.get("ref", "")),
            )
        )

    return ArtifactManifest(
        schema=str(schema),
        built_at=built_at,
        trigger=trigger,
        artifacts=artifacts,
    )
