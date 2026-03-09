"""Build detail panel — shows step summary and artifact manifest."""

from __future__ import annotations

import contextlib
import logging
import webbrowser
from typing import ClassVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Middle
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import DataTable, Label, LoadingIndicator, Markdown

from ..api import GitHubClient, RunData
from ..config import RepoConfig
from ..schema import ArtifactManifest, extract_manifest, parse_manifest_json

logger = logging.getLogger(__name__)


class DetailPanel(Widget):
    """Build detail and artifact view — used directly in split mode,
    or embedded inside DetailScreen for modal mode."""

    DEFAULT_CSS: ClassVar[str] = """
    DetailPanel {
        width: 1fr;
        height: 100%;
        background: $surface;
        border-left: solid $accent;
        padding: 1 2;
    }

    DetailPanel #dp-title {
        text-style: bold;
        color: $text;
        margin-bottom: 0;
    }

    DetailPanel #dp-commit-msg {
        color: $text-muted;
        text-style: italic;
        margin-bottom: 1;
    }

    DetailPanel #dp-loading {
        height: 3;
    }

    DetailPanel #dp-error {
        color: $warning;
        margin-top: 1;
    }

    DetailPanel #dp-release {
        color: $text-muted;
        margin-top: 1;
    }

    DetailPanel #dp-artifact-table {
        height: auto;
        margin-bottom: 1;
    }

    DetailPanel #dp-summary {
        height: 1fr;
        overflow-y: auto;
        margin-top: 1;
    }

    DetailPanel #dp-loading-container {
        height: 1fr;
        align: center middle;
    }

    DetailPanel #dp-loading {
        width: auto;
        height: auto;
    }

    DetailPanel #dp-loading-label {
        color: $text-muted;
        margin-top: 1;
    }
    """

    can_focus: ClassVar[bool] = True

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("c", "copy_ref", "Copy ref", show=False),
        Binding("t", "copy_tag", "Copy tag", show=False),
    ]

    def __init__(
        self,
        client: GitHubClient,
        repo: RepoConfig,
        run: RunData,
        auto_focus_table: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._client = client
        self._repo = repo
        self._run = run
        self._auto_focus_table = auto_focus_table
        self._summary_text: str | None = None
        self._manifest: ArtifactManifest | None = None
        self._release_tag: str | None = None

    def compose(self) -> ComposeResult:
        alias = self._repo.alias or self._repo.repo
        branch = self._run.head_branch or self._repo.watch_branch or "—"
        yield Label(f"{alias}  ·  {branch}", id="dp-title")
        commit_msg = self._format_commit_message(self._run.head_commit_message)
        yield Label(commit_msg, id="dp-commit-msg")
        with Middle(id="dp-loading-container"):
            with Center():
                yield LoadingIndicator(id="dp-loading")
            with Center():
                yield Label("Fetching build details…", id="dp-loading-label")

    def on_mount(self) -> None:
        self._load_data()

    @work(exclusive=True, group="detail-load")
    async def _load_data(self) -> None:
        """Fetch manifest and/or summary data, then render the panel contents.

        Uses the persistent detail cache to avoid redundant API calls.  On a
        cache miss the result is stored for future lookups.
        """
        run_id = self._run.run_id
        owner = self._repo.owner
        repo = self._repo.repo
        repo_key = self._repo.key
        updated_at = self._run.updated_at.isoformat() if self._run.updated_at else ""

        # 1. Check detail cache
        cached = self._client.detail_cache.get(repo_key, run_id, updated_at)
        if cached is not None:
            logger.debug("Detail cache hit for %s run %s", repo_key, run_id)
            if cached.manifest_json:
                self._manifest = parse_manifest_json(cached.manifest_json)
            self._summary_text = cached.summary_text
            self._release_tag = cached.release_tag
            await self._render_content()
            return

        logger.debug("Detail cache miss for %s run %s — fetching from API", repo_key, run_id)

        # 2. Artifact-based manifest
        try:
            self._manifest = await self._client.get_manifest_from_artifact(owner, repo, run_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Error fetching manifest artifact for %s/%s run %s: %s",
                owner, repo, run_id, exc,
            )

        # 3. Step summary with hint
        hint = self._client.manifest_hints.get_summary_job(repo_key)
        try:
            self._summary_text, job_name = await self._client.get_step_summary(
                owner, repo, run_id, hint_job_name=hint,
            )
            if job_name:
                self._client.manifest_hints.set_summary_job(repo_key, job_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Error fetching step summary for %s/%s run %s: %s",
                owner, repo, run_id, exc,
            )

        if not self._manifest and self._summary_text:
            self._manifest = extract_manifest(self._summary_text)

        # 4. Fall back to latest release tag
        if not self._manifest:
            try:
                self._release_tag = await self._client.get_latest_release(owner, repo)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error fetching latest release for %s/%s: %s", owner, repo, exc)

        # 5. Store in detail cache
        manifest_json: str | None = None
        if self._manifest:
            import json as _json
            manifest_json = _json.dumps({
                "schema": self._manifest.schema,
                "built_at": (
                    self._manifest.built_at.isoformat() if self._manifest.built_at else None
                ),
                "trigger": self._manifest.trigger,
                "artifacts": [
                    {"name": a.name, "type": a.type, "version": a.version, "ref": a.ref}
                    for a in self._manifest.artifacts
                ],
            })

        from ..detail_cache import DetailEntry
        self._client.detail_cache.put(
            repo_key, run_id, updated_at,
            DetailEntry(
                manifest_json=manifest_json,
                summary_text=self._summary_text,
                release_tag=self._release_tag,
            ),
        )

        await self._render_content()

    async def _render_content(self) -> None:
        """Remove the loading indicator and mount the actual content widgets."""
        # Remove any existing content (guards against race conditions on fast switching)
        for widget_id in ("#dp-loading-container", "#dp-artifact-table", "#dp-summary",
                          "#dp-release"):
            with contextlib.suppress(Exception):
                await self.query_one(widget_id).remove()

        if self._manifest and self._manifest.artifacts:
            table: DataTable[str] = DataTable(id="dp-artifact-table")
            await self.mount(table)
            table.add_columns("name", "type", "version", "ref")
            for item in self._manifest.artifacts:
                table.add_row(item.name, item.type, item.version, item.ref)
            if self._auto_focus_table:
                self.app.call_after_refresh(table.focus)

        if self._summary_text:
            await self.mount(Markdown(self._summary_text, id="dp-summary"))
        elif self._release_tag:
            await self.mount(Label(f"Latest release: {self._release_tag}", id="dp-release"))
        elif not self._manifest:
            await self.mount(Label(
                f"No summary available — run status: {self._run.display_status}",
                id="dp-release",
            ))

    async def update_for_run(self, repo: RepoConfig, run: RunData) -> None:
        """Switch the panel to show a different repo/run.

        Removes existing content, updates internal state, and triggers a
        fresh data load (which will hit the cache if available).
        """
        self._repo = repo
        self._run = run
        self._manifest = None
        self._summary_text = None
        self._release_tag = None

        # Update title and commit message
        alias = repo.alias or repo.repo
        branch = run.head_branch or repo.watch_branch or "—"
        with contextlib.suppress(Exception):
            self.query_one("#dp-title", Label).update(f"{alias}  ·  {branch}")
        with contextlib.suppress(Exception):
            self.query_one("#dp-commit-msg", Label).update(
                self._format_commit_message(run.head_commit_message)
            )

        # Remove existing content widgets
        content_ids = (
            "#dp-artifact-table", "#dp-summary", "#dp-release", "#dp-loading-container",
        )
        for widget_id in content_ids:
            with contextlib.suppress(Exception):
                await self.query_one(widget_id).remove()

        # Show loading indicator and start data load
        container = Middle(id="dp-loading-container")
        await self.mount(container)
        center1 = Center()
        await container.mount(center1)
        await center1.mount(LoadingIndicator(id="dp-loading"))
        center2 = Center()
        await container.mount(center2)
        await center2.mount(Label("Fetching build details…", id="dp-loading-label"))

        self._load_data()

    @staticmethod
    def _format_commit_message(message: str | None) -> str:
        if not message:
            return ""
        msg = message.replace("\n", " ").replace("\r", "").strip()
        return msg[:87] + "…" if len(msg) > 90 else msg

    def action_copy_ref(self) -> None:
        """Copy the ref of the selected artifact (or run URL) to the clipboard."""
        ref = self._get_copy_ref()
        if not ref:
            self.app.notify("Nothing to copy", timeout=2)
            return
        self._do_copy(ref)

    def action_copy_tag(self) -> None:
        """Copy the tag/version (part after ':' in ref) of the selected artifact."""
        tag = self._get_copy_tag()
        if not tag:
            self.app.notify("Nothing to copy", timeout=2)
            return
        self._do_copy(tag)

    @work(exclusive=False, group="clipboard")
    async def _do_copy(self, ref: str) -> None:
        """Write ref to the system clipboard using the first available tool."""
        import asyncio

        data = ref.encode()
        display = ref if len(ref) <= 60 else ref[:57] + "…"

        for cmd in [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except (FileNotFoundError, OSError):
                continue

            try:
                proc.stdin.write(data)
                await proc.stdin.drain()
                proc.stdin.close()
            except OSError:
                proc.kill()
                continue

            try:
                # wl-copy/xclip stay resident to serve paste requests — a
                # timeout here means the data was delivered successfully.
                await asyncio.wait_for(proc.wait(), timeout=1.0)
                if proc.returncode != 0:
                    continue
            except TimeoutError:
                # Process is running in the background serving the clipboard.
                pass

            self.app.notify(f"Ref '{display}' copied", timeout=2)
            return

        self.app.notify(
            "No clipboard tool found (wl-copy/xclip/xsel)", severity="warning", timeout=3,
        )

    def _get_copy_ref(self) -> str | None:
        """Return the ref to copy — focused artifact ref, or run URL as fallback."""
        if self._manifest and self._manifest.artifacts:
            try:
                table = self.query_one("#dp-artifact-table", DataTable)
                idx = table.cursor_row
                if 0 <= idx < len(self._manifest.artifacts):
                    return self._manifest.artifacts[idx].ref
            except Exception:  # noqa: BLE001
                pass
        if self._run.html_url:
            return self._run.html_url
        return None

    def _get_copy_tag(self) -> str | None:
        """Return the tag/version to copy — part after ':' in ref, or version field."""
        if self._manifest and self._manifest.artifacts:
            try:
                table = self.query_one("#dp-artifact-table", DataTable)
                idx = table.cursor_row
                if 0 <= idx < len(self._manifest.artifacts):
                    item = self._manifest.artifacts[idx]
                    if ":" in item.ref:
                        return item.ref.rsplit(":", 1)[-1]
                    if item.version:
                        return item.version
            except Exception:  # noqa: BLE001
                pass
        return None

    def open_browser(self) -> None:
        if self._run.html_url:
            logger.debug("Opening browser: %s", self._run.html_url)
            webbrowser.open(self._run.html_url)


class DetailScreen(ModalScreen[None]):
    """True modal screen wrapping the detail panel.

    Used when the terminal is narrower than 120 columns (or when
    ``detail_layout = "modal"`` is set in config). Captures all keyboard
    input so the repo list underneath is fully inert while it is open.
    """

    DEFAULT_CSS: ClassVar[str] = """
    DetailScreen {
        align: center middle;
    }

    DetailScreen > DetailPanel {
        width: 80%;
        height: 80%;
        border: round $accent;
        border-left: round $accent;
        padding: 1 2;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss", "Close", priority=True),
        Binding("o", "open_browser", "Open in browser", show=False),
        Binding("c", "copy_ref", "Copy ref", show=False),
        Binding("t", "copy_tag", "Copy tag", show=False),
    ]

    def __init__(
        self,
        client: GitHubClient,
        repo: RepoConfig,
        run: RunData,
    ) -> None:
        super().__init__()
        self._client = client
        self._repo = repo
        self._run = run

    def compose(self) -> ComposeResult:
        yield DetailPanel(
            client=self._client,
            repo=self._repo,
            run=self._run,
            auto_focus_table=True,
            id="detail-panel",
        )

    def action_open_browser(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#detail-panel", DetailPanel).open_browser()

    def action_copy_ref(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#detail-panel", DetailPanel).action_copy_ref()

    def action_copy_tag(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#detail-panel", DetailPanel).action_copy_tag()
