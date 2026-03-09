"""GitHub API client with ETag caching and state diffing."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import DETAIL_CACHE_PATH, ETAGS_PATH, MANIFEST_HINTS_PATH, STATE_PATH
from .detail_cache import DetailCache
from .manifest_hints import ManifestHints
from .schema import ArtifactManifest, parse_manifest_json

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


@dataclass
class RunData:
    """Data about a single GitHub Actions run."""

    run_id: int
    status: str           # queued | in_progress | completed
    conclusion: str | None  # success | failure | cancelled | skipped | None
    html_url: str
    run_started_at: datetime | None
    updated_at: datetime | None
    head_branch: str | None
    head_commit_message: str | None         # commit message that triggered the run
    last_completed_status: str | None       # conclusion of the last completed run
    last_completed_updated_at: datetime | None  # updated_at of the last completed run

    @property
    def display_status(self) -> str:
        """Status string for display: conclusion if completed, else status."""
        if self.status == "completed" and self.conclusion:
            return self.conclusion
        return self.status


@dataclass
class RateLimitInfo:
    """Rate limit information from response headers."""

    remaining: int
    reset_at: datetime | None
    limit: int


@dataclass
class PollResult:
    """Result of polling a single repo."""

    run: RunData | None
    rate_limit: RateLimitInfo | None
    cached: bool          # True if 304 Not Modified
    error: str | None     # Human-readable error message, if any
    transitioned: bool    # True if run ID or status changed since last poll
    previous_status: str | None  # Status before transition, if transitioned


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.debug("Cannot parse datetime: %s", value)
        return None


def _parse_rate_limit(headers: httpx.Headers) -> RateLimitInfo | None:
    try:
        remaining = int(headers.get("x-ratelimit-remaining", -1))
        limit = int(headers.get("x-ratelimit-limit", -1))
        reset_ts = headers.get("x-ratelimit-reset")
        reset_at: datetime | None = None
        if reset_ts:
            reset_at = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc)
        return RateLimitInfo(remaining=remaining, reset_at=reset_at, limit=limit)
    except (ValueError, TypeError):
        return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to save %s: %s", path, exc)


class GitHubClient:
    """Async GitHub API client with ETag caching and state diffing."""

    def __init__(self, pat: str) -> None:
        self._pat = pat
        self._client: httpx.AsyncClient | None = None
        self._etags: dict[str, str] = {}
        self._cached_runs: dict[str, dict[str, Any]] = {}
        self._state: dict[str, dict[str, Any]] = {}
        self.detail_cache = DetailCache(DETAIL_CACHE_PATH)
        self.manifest_hints = ManifestHints(MANIFEST_HINTS_PATH)

    async def __aenter__(self) -> "GitHubClient":
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API,
            headers={
                "Authorization": f"Bearer {self._pat}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        self._etags = _load_json(ETAGS_PATH)
        self._state = _load_json(STATE_PATH)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()
        _save_json(ETAGS_PATH, self._etags)
        _save_json(STATE_PATH, self._state)
        self.detail_cache.save()
        self.manifest_hints.save()

    async def validate_pat(self) -> str | None:
        """Validate PAT by calling GET /user. Returns GitHub login or None on failure."""
        if not self._client:
            raise RuntimeError("Client not initialised — use async context manager")
        try:
            resp = await self._client.get("/user")
            if resp.status_code == 200:
                return str(resp.json().get("login", ""))
            logger.warning("PAT validation failed: HTTP %s", resp.status_code)
            return None
        except httpx.RequestError as exc:
            logger.warning("PAT validation network error: %s", exc)
            return None

    async def get_latest_run(
        self,
        owner: str,
        repo: str,
        branch: str | None = None,
    ) -> PollResult:
        """Fetch the latest Actions run for a repo.

        Uses ETag conditional requests to avoid unnecessary data transfer.
        Detects state transitions by comparing against persisted state.
        """
        if not self._client:
            raise RuntimeError("Client not initialised — use async context manager")

        repo_key = f"{owner}/{repo}"
        params: dict[str, str | int] = {"per_page": 1}
        if branch:
            params["branch"] = branch

        url = f"/repos/{owner}/{repo}/actions/runs"
        headers: dict[str, str] = {}
        etag_key = f"{repo_key}?branch={branch or ''}"
        if etag := self._etags.get(etag_key):
            headers["If-None-Match"] = etag

        try:
            resp = await self._client.get(url, params=params, headers=headers)
            logger.debug("%s %s -> HTTP %s", "GET", url, resp.status_code)
        except httpx.RequestError as exc:
            logger.warning("Network error fetching %s: %s", repo_key, exc)
            # Return last known run from cache if available
            cached_run = self._build_run_from_state(repo_key)
            return PollResult(
                run=cached_run,
                rate_limit=None,
                cached=True,
                error=f"Network error: {exc}",
                transitioned=False,
                previous_status=None,
            )

        rate_limit = _parse_rate_limit(resp.headers)

        if resp.status_code == 304:
            logger.debug("304 Not Modified for %s — using cached data", repo_key)
            cached_run = self._build_run_from_state(repo_key)
            return PollResult(
                run=cached_run,
                rate_limit=rate_limit,
                cached=True,
                error=None,
                transitioned=False,
                previous_status=None,
            )

        if resp.status_code in (401, 403):
            logger.warning("Auth error for %s: HTTP %s", repo_key, resp.status_code)
            if resp.status_code == 403:
                reset_msg = ""
                if rate_limit and rate_limit.reset_at:
                    reset_msg = f" (resets at {rate_limit.reset_at.strftime('%H:%M:%S')})"
                error = f"Rate limited{reset_msg}"
            else:
                error = "Authentication failed — check your PAT"
            return PollResult(
                run=self._build_run_from_state(repo_key),
                rate_limit=rate_limit,
                cached=True,
                error=error,
                transitioned=False,
                previous_status=None,
            )

        if resp.status_code == 404:
            logger.warning("Repo not found: %s", repo_key)
            return PollResult(
                run=None,
                rate_limit=rate_limit,
                cached=False,
                error="Repository not found",
                transitioned=False,
                previous_status=None,
            )

        if resp.status_code != 200:
            logger.warning("Unexpected status %s for %s", resp.status_code, repo_key)
            return PollResult(
                run=self._build_run_from_state(repo_key),
                rate_limit=rate_limit,
                cached=True,
                error=f"API error: HTTP {resp.status_code}",
                transitioned=False,
                previous_status=None,
            )

        # Store ETag for next request
        if etag := resp.headers.get("etag"):
            self._etags[etag_key] = etag

        data = resp.json()
        runs = data.get("workflow_runs", [])
        if not runs:
            return PollResult(
                run=None,
                rate_limit=rate_limit,
                cached=False,
                error=None,
                transitioned=False,
                previous_status=None,
            )

        raw_run = runs[0]
        prev_state = self._state.get(repo_key, {})
        run = self._parse_run(raw_run, prev_state)

        # State diffing
        prev_run_id = prev_state.get("run_id")
        prev_status = prev_state.get("display_status")
        current_status = run.display_status

        transitioned = (prev_run_id != run.run_id) or (prev_status != current_status)

        # Update persisted state — carry forward last_completed fields as needed
        new_state: dict[str, Any] = {
            "run_id": run.run_id,
            "display_status": current_status,
            "html_url": run.html_url,
            "status": run.status,
            "conclusion": run.conclusion,
            "run_started_at": run.run_started_at.isoformat() if run.run_started_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            "head_branch": run.head_branch,
            "head_commit_message": run.head_commit_message,
            "last_completed_status": run.last_completed_status,
            "last_completed_updated_at": (
                run.last_completed_updated_at.isoformat()
                if run.last_completed_updated_at
                else None
            ),
        }
        self._state[repo_key] = new_state

        return PollResult(
            run=run,
            rate_limit=rate_limit,
            cached=False,
            error=None,
            transitioned=transitioned,
            previous_status=prev_status if transitioned else None,
        )

    def _parse_run(self, raw: dict[str, Any], prev_state: dict[str, Any]) -> RunData:
        """Parse a raw API run dict into a RunData dataclass.

        When the current run is in_progress or queued, the last_completed_* fields
        are carried forward from the previous persisted state.  When it is completed,
        they are set from the current run's conclusion and updated_at.
        """
        status = str(raw.get("status", "unknown"))
        conclusion: str | None = raw.get("conclusion")
        updated_at = _parse_datetime(raw.get("updated_at"))

        if status == "completed" and conclusion:
            last_completed_status: str | None = conclusion
            last_completed_updated_at: datetime | None = updated_at
        else:
            # Preserve whatever was stored from a previous completed run
            last_completed_status = prev_state.get("last_completed_status")
            last_completed_updated_at = _parse_datetime(
                prev_state.get("last_completed_updated_at")
            )

        head_commit = raw.get("head_commit") or {}
        head_commit_message: str | None = head_commit.get("message") if head_commit else None

        return RunData(
            run_id=int(raw.get("id", 0)),
            status=status,
            conclusion=conclusion,
            html_url=str(raw.get("html_url", "")),
            run_started_at=_parse_datetime(raw.get("run_started_at")),
            updated_at=updated_at,
            head_branch=raw.get("head_branch"),
            head_commit_message=head_commit_message,
            last_completed_status=last_completed_status,
            last_completed_updated_at=last_completed_updated_at,
        )

    def _build_run_from_state(self, repo_key: str) -> RunData | None:
        """Reconstruct a RunData from persisted state, or None if no state exists."""
        state = self._state.get(repo_key)
        if not state:
            return None
        return RunData(
            run_id=int(state.get("run_id", 0)),
            status=str(state.get("status", "unknown")),
            conclusion=state.get("conclusion"),
            html_url=str(state.get("html_url", "")),
            run_started_at=_parse_datetime(state.get("run_started_at")),
            updated_at=_parse_datetime(state.get("updated_at")),
            head_branch=state.get("head_branch"),
            head_commit_message=state.get("head_commit_message"),
            last_completed_status=state.get("last_completed_status"),
            last_completed_updated_at=_parse_datetime(
                state.get("last_completed_updated_at")
            ),
        )

    async def get_manifest_from_artifact(
        self, owner: str, repo: str, run_id: int
    ) -> ArtifactManifest | None:
        """Download all 'ghastly-manifest*' Actions artifacts and merge their contents.

        Multiple jobs can each upload a ghastly-manifest artifact with a unique
        suffix (e.g. ghastly-manifest-api, ghastly-manifest-frontend).  This method
        collects all of them and merges their artifact lists into one manifest.

        Returns a merged ArtifactManifest, or None if no valid manifest is found.
        Never raises.
        """
        if not self._client:
            raise RuntimeError("Client not initialised — use async context manager")

        url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts"
        logger.debug("GET %s", url)
        try:
            resp = await self._client.get(url, params={"per_page": 100})
        except httpx.RequestError as exc:
            logger.warning("Network error listing artifacts for run %s: %s", run_id, exc)
            return None

        if resp.status_code != 200:
            logger.warning("Unexpected status %s listing artifacts for run %s", resp.status_code, run_id)
            return None

        merged: ArtifactManifest | None = None

        for artifact in resp.json().get("artifacts", []):
            if not str(artifact.get("name", "")).startswith("ghastly-manifest"):
                continue

            download_url = str(artifact.get("archive_download_url", ""))
            if not download_url:
                continue

            logger.debug("Downloading %s artifact: %s", artifact.get("name"), download_url)
            try:
                zip_resp = await self._client.get(download_url, follow_redirects=True)
            except httpx.RequestError as exc:
                logger.warning("Network error downloading %s: %s", artifact.get("name"), exc)
                continue

            if zip_resp.status_code != 200:
                logger.warning(
                    "Unexpected status %s downloading %s", zip_resp.status_code, artifact.get("name")
                )
                continue

            try:
                with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
                    for name in zf.namelist():
                        raw = zf.read(name).decode("utf-8").strip()
                        if not raw:
                            continue
                        manifest = parse_manifest_json(raw)
                        if manifest is None:
                            continue
                        if merged is None:
                            merged = manifest
                        else:
                            merged.artifacts.extend(manifest.artifacts)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to unzip %s: %s", artifact.get("name"), exc)

        return merged

    async def get_step_summary(
        self,
        owner: str,
        repo: str,
        run_id: int,
        *,
        hint_job_name: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Fetch the step summary markdown for a run, if available.

        When ``hint_job_name`` is provided, that job is tried first before
        iterating all jobs — significantly reducing API calls for repos with
        many jobs (e.g. monorepos).

        Returns ``(summary_text, job_name)`` where *job_name* is the name of
        the job that contained the summary (for updating the hint), or
        ``(None, None)`` if no summary was found.
        """
        if not self._client:
            raise RuntimeError("Client not initialised — use async context manager")

        jobs_url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"
        logger.debug("GET %s", jobs_url)
        try:
            resp = await self._client.get(jobs_url, params={"per_page": 100})
        except httpx.RequestError as exc:
            logger.warning("Network error fetching jobs for run %s: %s", run_id, exc)
            return None, None

        if resp.status_code != 200:
            logger.warning("Unexpected status %s fetching jobs for run %s", resp.status_code, run_id)
            return None, None

        jobs = resp.json().get("jobs", [])

        # If we have a hint, try that job first
        if hint_job_name:
            for job in jobs:
                if job.get("name") == hint_job_name:
                    result = await self._fetch_job_summary(owner, repo, job.get("id"))
                    if result:
                        return result, hint_job_name
                    break  # Hint job found but no summary — fall through

        # Full iteration (skipping hinted job if already tried)
        for job in jobs:
            job_name = job.get("name", "")
            if hint_job_name and job_name == hint_job_name:
                continue  # Already tried above
            job_id = job.get("id")
            if not job_id:
                continue
            result = await self._fetch_job_summary(owner, repo, job_id)
            if result:
                return result, job_name

        return None, None

    async def _fetch_job_summary(
        self, owner: str, repo: str, job_id: int | None
    ) -> str | None:
        """Fetch the check-run summary for a single job. Returns summary text or None."""
        if not job_id or not self._client:
            return None
        check_url = f"/repos/{owner}/{repo}/check-runs/{job_id}"
        logger.debug("GET %s", check_url)
        try:
            check_resp = await self._client.get(check_url)
        except httpx.RequestError as exc:
            logger.warning("Network error fetching check-run %s: %s", job_id, exc)
            return None
        if check_resp.status_code != 200:
            return None
        summary = check_resp.json().get("output", {}).get("summary")
        if summary:
            return str(summary)
        return None

    async def get_latest_release(self, owner: str, repo: str) -> str | None:
        """Return the tag_name of the latest release, or None if unavailable."""
        if not self._client:
            raise RuntimeError("Client not initialised — use async context manager")

        url = f"/repos/{owner}/{repo}/releases/latest"
        logger.debug("GET %s", url)
        try:
            resp = await self._client.get(url)
        except httpx.RequestError as exc:
            logger.warning("Network error fetching latest release for %s/%s: %s", owner, repo, exc)
            return None

        if resp.status_code != 200:
            logger.warning("Unexpected status %s fetching latest release for %s/%s", resp.status_code, owner, repo)
            return None

        return str(resp.json().get("tag_name", "")) or None

    async def rerun_failed_jobs(self, owner: str, repo: str, run_id: int) -> bool:
        """Trigger a re-run of only the failed jobs for the given run.

        Returns True on HTTP 201, False otherwise.
        Logs a specific message on 403 (missing scope).
        """
        if not self._client:
            raise RuntimeError("Client not initialised — use async context manager")

        url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs"
        logger.debug("POST %s", url)
        try:
            resp = await self._client.post(url, json={})
        except httpx.RequestError as exc:
            logger.warning("Network error re-running failed jobs for run %s: %s", run_id, exc)
            return False

        if resp.status_code == 403:
            body = resp.text
            logger.warning(
                "403 re-running failed jobs for run %s — check PAT has actions:write scope. Body: %s",
                run_id,
                body[:200],
            )
            return False

        if resp.status_code != 201:
            logger.warning(
                "Unexpected HTTP %s re-running failed jobs for run %s", resp.status_code, run_id
            )
            return False

        logger.info("Re-run of failed jobs triggered for run %s", run_id)
        return True

    async def rerun_all(self, owner: str, repo: str, run_id: int) -> bool:
        """Trigger a full re-run of all jobs for the given run.

        Returns True on HTTP 201, False otherwise.
        Logs a specific message on 403 (missing scope).
        """
        if not self._client:
            raise RuntimeError("Client not initialised — use async context manager")

        url = f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun"
        logger.debug("POST %s", url)
        try:
            resp = await self._client.post(url, json={})
        except httpx.RequestError as exc:
            logger.warning("Network error re-running all jobs for run %s: %s", run_id, exc)
            return False

        if resp.status_code == 403:
            body = resp.text
            logger.warning(
                "403 re-running all jobs for run %s — check PAT has actions:write scope. Body: %s",
                run_id,
                body[:200],
            )
            return False

        if resp.status_code != 201:
            logger.warning(
                "Unexpected HTTP %s re-running all jobs for run %s", resp.status_code, run_id
            )
            return False

        logger.info("Full re-run triggered for run %s", run_id)
        return True

    def flush(self) -> None:
        """Persist ETags, state, detail cache, and manifest hints to disk immediately."""
        _save_json(ETAGS_PATH, self._etags)
        _save_json(STATE_PATH, self._state)
        self.detail_cache.save()
        self.manifest_hints.save()

    def clear_etags(self) -> None:
        """Drop all cached ETags, forcing fresh 200 responses on next poll."""
        self._etags.clear()
        _save_json(ETAGS_PATH, self._etags)
