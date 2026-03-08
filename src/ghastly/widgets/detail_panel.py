"""Build detail panel — shows step summary and artifact manifest."""

from __future__ import annotations

import logging
import webbrowser
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Label, LoadingIndicator, Markdown

from ..api import GitHubClient, RunData
from ..config import RepoConfig
from ..schema import ArtifactManifest, extract_manifest

logger = logging.getLogger(__name__)


class DetailPanel(Widget):
    """Build detail and artifact view.

    Supports two layout modes:
    - modal: floating overlay centred on screen (used when terminal < 120 cols)
    - split: mounted beside the repo list in a horizontal container (≥ 120 cols)

    The ``split_mode`` flag is set by the app before mounting.
    """

    # CSS for modal (overlay) mode
    MODAL_CSS: ClassVar[str] = """
    DetailPanel.modal-mode {
        width: 80%;
        height: 80%;
        background: $surface;
        border: round $accent;
        padding: 1 2;
        layer: dialog;
        offset-x: 10%;
        offset-y: 10%;
    }
    """

    # CSS for split (side panel) mode
    SPLIT_CSS: ClassVar[str] = """
    DetailPanel.split-mode {
        width: 1fr;
        height: 100%;
        background: $surface;
        border-left: solid $accent;
        padding: 1 2;
    }
    """

    DEFAULT_CSS: ClassVar[str] = MODAL_CSS + SPLIT_CSS + """
    DetailPanel #dp-title {
        text-style: bold;
        color: $text;
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
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", priority=True),
        Binding("o", "open_browser", "Open in browser"),
    ]

    class Close(Message):
        """Posted when the panel requests to be dismissed."""

    def __init__(
        self,
        client: GitHubClient,
        repo: RepoConfig,
        run: RunData,
        split_mode: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._client = client
        self._repo = repo
        self._run = run
        self._split_mode = split_mode
        self._summary_text: str | None = None
        self._manifest: ArtifactManifest | None = None
        self._release_tag: str | None = None
        self._load_error: str | None = None

    def compose(self) -> ComposeResult:
        alias = self._repo.alias or self._repo.repo
        branch = self._run.head_branch or self._repo.watch_branch or "—"
        yield Label(f"{alias}  ·  {branch}  ·  {self._run.html_url}", id="dp-title")
        yield LoadingIndicator(id="dp-loading")

    async def on_mount(self) -> None:
        # Apply the correct CSS class based on layout mode
        if self._split_mode:
            self.add_class("split-mode")
        else:
            self.add_class("modal-mode")
        await self._load_data()

    async def _load_data(self) -> None:
        """Fetch summary and/or release data, then render the panel contents."""
        run_id = self._run.run_id
        owner = self._repo.owner
        repo = self._repo.repo

        # Attempt to fetch step summary
        try:
            self._summary_text = await self._client.get_step_summary(owner, repo, run_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error fetching step summary for %s/%s run %s: %s", owner, repo, run_id, exc)
            self._summary_text = None

        if self._summary_text:
            self._manifest = extract_manifest(self._summary_text)

        # Fall back to latest release if no manifest
        if not self._manifest:
            try:
                self._release_tag = await self._client.get_latest_release(owner, repo)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error fetching latest release for %s/%s: %s", owner, repo, exc)

        await self._render_content()

    async def _render_content(self) -> None:
        """Remove the loading indicator and mount the actual content widgets."""
        try:
            loading = self.query_one("#dp-loading", LoadingIndicator)
            await loading.remove()
        except Exception:  # noqa: BLE001
            pass

        if self._manifest and self._manifest.artifacts:
            table: DataTable[str] = DataTable(id="dp-artifact-table")
            await self.mount(table)
            table.add_columns("name", "type", "version", "ref")
            for item in self._manifest.artifacts:
                table.add_row(item.name, item.type, item.version, item.ref)

        if self._summary_text:
            md = Markdown(self._summary_text, id="dp-summary")
            await self.mount(md)
        elif self._release_tag:
            await self.mount(Label(f"Latest release: {self._release_tag}", id="dp-release"))
        else:
            status = self._run.display_status
            await self.mount(Label(f"No summary available — run status: {status}", id="dp-release"))

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def action_close(self) -> None:
        self.post_message(self.Close())

    def action_open_browser(self) -> None:
        url = self._run.html_url
        if url:
            logger.debug("Opening browser: %s", url)
            webbrowser.open(url)
