"""ghastly Textual TUI application."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Footer, Header, Label, Static

from .api import GitHubClient, PollResult, RateLimitInfo, RunData
from .config import CONFIG_PATH, Config, RepoConfig, load_config
from .notifications import notify, urgency_for_status
from .widgets.detail_panel import DetailPanel, DetailScreen
from .widgets.filter_bar import FilterBar, matches
from .widgets.group_header import GroupHeader, aggregate_status
from .widgets.repo_row import RepoRow

logger = logging.getLogger(__name__)

# Minimum terminal width to use split mode when layout is "auto"
_SPLIT_WIDTH_THRESHOLD = 120


def _setup_logging(log_level: str, log_path: Path) -> None:
    """Configure file-based logging."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    numeric = getattr(logging, log_level.upper(), logging.WARNING)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )


# ------------------------------------------------------------------ #
# Sort mode
# ------------------------------------------------------------------ #

class SortMode(Enum):
    LAST_RUN = auto()
    STATUS = auto()
    ALIAS = auto()


_SORT_LABELS: dict[SortMode, str] = {
    SortMode.LAST_RUN: "last run",
    SortMode.STATUS: "status",
    SortMode.ALIAS: "alias",
}

_SORT_CYCLE: list[SortMode] = [SortMode.LAST_RUN, SortMode.STATUS, SortMode.ALIAS]


# ------------------------------------------------------------------ #
# Status bar
# ------------------------------------------------------------------ #

class StatusBar(Static):
    """Bottom status bar showing poll info, rate limit, and current sort."""

    DEFAULT_CSS: ClassVar[str] = """
    StatusBar {
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 1;
        layout: horizontal;
    }
    StatusBar #sb-left {
        width: 1fr;
    }
    StatusBar #sb-right {
        width: auto;
    }
    """

    last_poll: reactive[datetime | None] = reactive(None)
    next_poll_in: reactive[int] = reactive(0)
    repo_count: reactive[int] = reactive(0)
    rate_limit: reactive[RateLimitInfo | None] = reactive(None)
    offline: reactive[bool] = reactive(False)
    sort_mode: reactive[SortMode] = reactive(SortMode.LAST_RUN)

    def compose(self) -> ComposeResult:
        yield Label("", id="sb-left")
        yield Label("", id="sb-right")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self._refresh_labels()
        if self.next_poll_in > 0:
            self.next_poll_in -= 1

    def _refresh_labels(self) -> None:
        left_parts: list[str] = []

        if self.offline:
            left_parts.append("[offline]")

        if self.last_poll:
            ts = self.last_poll.strftime("%H:%M:%S")
            left_parts.append(f"last poll: {ts}")

        if self.next_poll_in > 0:
            left_parts.append(f"next in {self.next_poll_in}s")

        left_parts.append(f"{self.repo_count} repos")
        left_parts.append(f"sort: {_SORT_LABELS[self.sort_mode]}")

        right_parts: list[str] = []
        if self.rate_limit and self.rate_limit.remaining >= 0:
            right_parts.append(f"rate limit: {self.rate_limit.remaining}/{self.rate_limit.limit}")
            if self.rate_limit.remaining < 100 and self.rate_limit.reset_at:
                reset_str = self.rate_limit.reset_at.strftime("%H:%M:%S")
                right_parts.append(f"(resets {reset_str})")

        try:
            self.query_one("#sb-left", Label).update(" · ".join(left_parts))
            self.query_one("#sb-right", Label).update(" ".join(right_parts))
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ #
# Help screen
# ------------------------------------------------------------------ #

_HELP_TEXT = """\
┌─────────────────────────────────────────────┐
│              ghastly — keybindings          │
├─────────────────────────────────────────────┤
│ Navigation                                  │
│   ↑ / k        Move up                      │
│   ↓ / j        Move down                    │
│   ← / h        Collapse group / close detail│
│   → / l        Expand group / open detail   │
│                                             │
│ Global                                      │
│   q            Quit                         │
│   g            Toggle group view            │
│   s            Cycle sort order             │
│   /            Open filter                  │
│   r            Force refresh                │
│   ?            This help                    │
│                                             │
│ On selected row                             │
│   Enter / l    Open build detail            │
│   o            Open run in browser          │
│   R            Re-run failed jobs           │
│   Ctrl+R       Re-run entire workflow       │
│   C            Clear cache for repo         │
│                                             │
│   Press Esc or ? to close                  │
└─────────────────────────────────────────────┘\
"""


class HelpScreen(ModalScreen[None]):
    """Modal help overlay — dismissed by Esc or ?."""

    DEFAULT_CSS: ClassVar[str] = """
    HelpScreen {
        align: center middle;
    }

    HelpScreen #help-box {
        width: auto;
        height: auto;
        background: $surface;
        border: round $accent;
        padding: 1 2;
        color: $text;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("question_mark", "dismiss", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Static(_HELP_TEXT, id="help-box")

    def action_dismiss(self) -> None:  # type: ignore[override]
        self.dismiss()


# ------------------------------------------------------------------ #
# Pending rerun state
# ------------------------------------------------------------------ #

class _PendingRerun:
    """Tracks a pending rerun confirmation for a specific repo row."""

    def __init__(self, row: RepoRow, full: bool) -> None:
        self.row = row
        self.full = full  # True = rerun all; False = rerun failed jobs only


# ------------------------------------------------------------------ #
# Main application
# ------------------------------------------------------------------ #

class GhastlyApp(App[None]):
    """ghastly — GitHub Actions TUI monitor."""

    TITLE = "ghastly"
    CSS: ClassVar[str] = """
    Screen {
        layout: vertical;
    }

    #main-area {
        height: 1fr;
        layout: horizontal;
    }

    #repo-list {
        height: 100%;
        width: 1fr;
    }

    #col-header {
        height: 1;
        background: $surface-darken-2;
        layout: horizontal;
        padding: 0 1;
        color: $text-muted;
        text-style: bold;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_all", "Refresh"),
        Binding("?", "show_help", "Help"),
        Binding("g", "toggle_group", "Group", show=False),
        Binding("s", "cycle_sort", "Sort", show=False),
        Binding("slash", "open_filter", "Filter", show=False),
        Binding("j", "focus_next_row", "Down", show=False),
        Binding("k", "focus_prev_row", "Up", show=False),
        Binding("down", "focus_next_row", "Down", show=False),
        Binding("up", "focus_prev_row", "Up", show=False),
        Binding("l", "expand_or_open", "Open/expand", show=False),
        Binding("right", "expand_or_open", "Open/expand", show=False),
        Binding("h", "collapse_or_close", "Close/collapse", show=False),
        Binding("left", "collapse_or_close", "Close/collapse", show=False),
        Binding("R", "rerun_failed", "Rerun failed", show=False),
        Binding("ctrl+r", "rerun_all_prompt", "Rerun all", show=False),
        Binding("o", "open_browser", "Open", show=False),
        Binding("C", "clear_repo_cache", "Clear cache", show=False),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._client: GitHubClient | None = None
        # repo key → RepoRow widget (always maintained)
        self._rows: dict[str, RepoRow] = {}
        self._status_bar: StatusBar | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._watch_task: asyncio.Task[None] | None = None
        self._config_path = CONFIG_PATH
        self._detail_panel: DetailPanel | None = None
        self._filter_bar: FilterBar | None = None
        self._filter_query: str = ""

        # Group view state
        self._group_view: bool = False
        # group_name → GroupHeader widget (only in group view)
        self._group_headers: dict[str, GroupHeader] = {}
        # group_name → collapsed state
        self._group_collapsed: dict[str, bool] = {}

        # Sort
        self._sort_mode: SortMode = SortMode.LAST_RUN

        # Rerun confirmation
        self._pending_rerun: _PendingRerun | None = None

        # Layout tracking
        self._split_mode: bool = False

    # ------------------------------------------------------------------ #
    # Compose
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            " alias                   branch           now          last build   age",
            id="col-header",
        )
        with Horizontal(id="main-area"):
            yield VerticalScroll(id="repo-list")
        fb = FilterBar(id="filter-bar")
        self._filter_bar = fb
        yield fb
        sb = StatusBar(id="status-bar")
        self._status_bar = sb
        yield sb
        yield Footer()

    # ------------------------------------------------------------------ #
    # Mount
    # ------------------------------------------------------------------ #

    def watch_theme(self, theme: str) -> None:
        """Persist theme changes to config."""
        if theme != self._config.display.theme:
            from .config import config_to_dict, write_config

            self._config.display.theme = theme
            write_config(config_to_dict(self._config), self._config_path)

    async def on_mount(self) -> None:
        from .config import DATA_DIR, LOG_PATH

        _setup_logging(self._config.log_level, LOG_PATH)
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Apply saved theme before anything else
        self.theme = self._config.display.theme

        self._client = GitHubClient(self._config.auth.pat)
        await self._client.__aenter__()

        # Populate initial repo rows (flat view)
        repo_list = self.query_one("#repo-list", VerticalScroll)
        for repo in self._config.repos:
            row = RepoRow(repo, id=f"row-{_safe_id(repo.key)}")
            self._rows[repo.key] = row
            await repo_list.mount(row)

        if self._status_bar:
            self._status_bar.repo_count = len(self._config.repos)

        # Focus the first row if present
        visible_rows = list(self._rows.values())
        if visible_rows:
            visible_rows[0].focus()

        # Adapt alias column width to longest alias
        self._update_alias_column_width()
        self._update_column_header()

        # Start polling and config watch
        self._start_polling()
        self._start_config_watch()

    async def on_unmount(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
        if self._watch_task:
            self._watch_task.cancel()
        if self._client:
            await self._client.__aexit__(None, None, None)

    # ------------------------------------------------------------------ #
    # Resize — adaptive layout
    # ------------------------------------------------------------------ #

    def on_resize(self, event: object) -> None:
        """Re-evaluate split vs. modal layout when terminal size changes."""
        new_split = self._should_use_split()
        if new_split != self._split_mode and self._detail_panel is not None:
            # Layout mode changed while detail panel is open — remount
            self._split_mode = new_split
            self.run_worker(self._remount_detail_panel(), exclusive=True)
        else:
            self._split_mode = new_split

    def _should_use_split(self) -> bool:
        """Return True if split layout should be used given current config and terminal width."""
        layout_cfg = self._config.display.detail_layout
        if layout_cfg == "modal":
            return False
        if layout_cfg == "split":
            return True
        # "auto" — decide by width
        try:
            return self.size.width >= _SPLIT_WIDTH_THRESHOLD
        except Exception:  # noqa: BLE001
            return False

    async def _remount_detail_panel(self) -> None:
        """Remount the detail panel in the new layout mode."""
        if self._detail_panel is None:
            return

        # Capture current row/run details before removing
        client = self._client
        if client is None:
            return

        repo = self._detail_panel._repo
        run = self._detail_panel._run

        # Remove old panel
        await self._detail_panel.remove()
        self._detail_panel = None

        # Remount in new mode
        await self._open_detail(repo, run)

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def action_refresh_all(self) -> None:
        """Force an immediate poll of all repos."""
        self._poll_now()

    def action_show_help(self) -> None:
        """Show the help overlay."""
        self.push_screen(HelpScreen())

    def action_toggle_group(self) -> None:
        """Toggle between flat and grouped repo views."""
        self.run_worker(self._toggle_group_view(), exclusive=True)

    def action_cycle_sort(self) -> None:
        """Cycle through sort modes."""
        current_idx = _SORT_CYCLE.index(self._sort_mode)
        self._sort_mode = _SORT_CYCLE[(current_idx + 1) % len(_SORT_CYCLE)]
        if self._status_bar:
            self._status_bar.sort_mode = self._sort_mode
        self.run_worker(self._apply_sort(), exclusive=False)

    def action_open_filter(self) -> None:
        """Open the filter bar."""
        if self._filter_bar:
            self._filter_bar.open()

    def action_focus_next_row(self) -> None:
        """Move focus to the next focusable row."""
        self._shift_focus(1)

    def action_focus_prev_row(self) -> None:
        """Move focus to the previous focusable row."""
        self._shift_focus(-1)

    def action_expand_or_open(self) -> None:
        """Expand a collapsed group header, or open the detail panel for a repo row."""
        focused = self.focused
        if isinstance(focused, GroupHeader):
            if not focused.expanded:
                focused.toggle()
        elif isinstance(focused, RepoRow):
            self.run_worker(self._open_detail_for_row(focused), exclusive=True)

    def action_collapse_or_close(self) -> None:
        """Collapse an expanded group header, or close the detail panel."""
        focused = self.focused
        if isinstance(focused, GroupHeader):
            if focused.expanded:
                focused.toggle()
        elif self._detail_panel is not None:
            self.run_worker(self._close_detail(), exclusive=True)

    def action_rerun_failed(self) -> None:
        """Prompt the user to re-run failed jobs on the focused row."""
        focused = self.focused
        if not isinstance(focused, RepoRow):
            return
        if focused.run is None:
            self.notify("No run data available", timeout=2)
            return
        self._pending_rerun = _PendingRerun(row=focused, full=False)
        self.notify("Press y to re-run failed jobs, n to cancel", timeout=5)

    def action_rerun_all_prompt(self) -> None:
        """Prompt the user to re-run all jobs on the focused row."""
        focused = self.focused
        if not isinstance(focused, RepoRow):
            return
        if focused.run is None:
            self.notify("No run data available", timeout=2)
            return
        self._pending_rerun = _PendingRerun(row=focused, full=True)
        self.notify("Press y to re-run all jobs, n to cancel", timeout=5)

    def action_open_browser(self) -> None:
        """Open the focused row's run URL in the default browser."""
        import webbrowser
        focused = self.focused
        if isinstance(focused, RepoRow) and focused.run:
            url = focused.run.html_url
            if url:
                webbrowser.open(url)

    def action_clear_repo_cache(self) -> None:
        """Clear detail cache and manifest hints for the focused repo."""
        focused = self.focused
        if not isinstance(focused, RepoRow):
            return
        if self._client is None:
            return
        repo_key = focused.repo.key
        self._client.detail_cache.clear_repo(repo_key)
        self._client.manifest_hints.clear_repo(repo_key)
        self._client.detail_cache.save()
        self._client.manifest_hints.save()
        self.notify(f"Cache cleared for {repo_key}", timeout=3)

    # ------------------------------------------------------------------ #
    # Key handler — for rerun confirmation and / shortcut
    # ------------------------------------------------------------------ #

    def on_key(self, event: object) -> None:
        from textual.events import Key
        if not isinstance(event, Key):
            return

        # Rerun confirmation
        if self._pending_rerun is not None:
            if event.key == "y":
                event.prevent_default()
                event.stop()
                pending = self._pending_rerun
                self._pending_rerun = None
                self.run_worker(self._do_rerun(pending), exclusive=False)
            elif event.key in ("n", "escape"):
                event.prevent_default()
                event.stop()
                self._pending_rerun = None
                self.notify("Rerun cancelled", timeout=2)

    # ------------------------------------------------------------------ #
    # Focus navigation
    # ------------------------------------------------------------------ #

    def _focusable_widgets(self) -> list[Widget]:
        """Return ordered list of currently focusable repo rows and group headers."""
        repo_list = self.query_one("#repo-list", VerticalScroll)
        result: list[Widget] = []
        for child in repo_list.children:
            if isinstance(child, (RepoRow, GroupHeader)) and child.display:
                result.append(child)
        return result

    def _shift_focus(self, delta: int) -> None:
        widgets = self._focusable_widgets()
        if not widgets:
            return
        focused = self.focused
        try:
            idx = widgets.index(focused)  # type: ignore[arg-type]
        except ValueError:
            widgets[0].focus()
            return
        new_idx = (idx + delta) % len(widgets)
        widgets[new_idx].focus()

        # Update detail panel to follow cursor in split mode
        new_widget = widgets[new_idx]
        if (
            self._split_mode
            and self._detail_panel is not None
            and isinstance(new_widget, RepoRow)
            and new_widget.run is not None
        ):
            self.run_worker(
                self._detail_panel.update_for_run(new_widget.repo, new_widget.run),
                exclusive=True,
            )

    # ------------------------------------------------------------------ #
    # Detail panel
    # ------------------------------------------------------------------ #

    async def on_repo_row_selected(self, message: RepoRow.Selected) -> None:
        """Open the detail panel when the user presses Enter on a row."""
        if self._detail_panel is not None:
            return

        row = message.row
        run = row.run
        if run is None:
            self.notify("No run data available yet", timeout=2)
            return

        await self._open_detail_for_row(row)

    async def _open_detail_for_row(self, row: RepoRow) -> None:
        if self._detail_panel is not None:
            return
        run = row.run
        if run is None:
            self.notify("No run data available yet", timeout=2)
            return
        await self._open_detail(row.repo, run)

    async def _open_detail(self, repo: RepoConfig, run: RunData) -> None:
        """Open the detail panel in the appropriate layout mode."""
        if self._client is None:
            return

        split = self._should_use_split()
        self._split_mode = split

        if split:
            panel = DetailPanel(
                client=self._client,
                repo=repo,
                run=run,
                id="detail-panel",
            )
            self._detail_panel = panel
            main_area = self.query_one("#main-area", Horizontal)
            repo_list = self.query_one("#repo-list", VerticalScroll)
            repo_list.styles.width = "1fr"
            await main_area.mount(panel)
        else:
            # True modal — push onto the screen stack so it captures all input
            await self.push_screen(DetailScreen(self._client, repo, run))

    async def _close_detail(self) -> None:
        """Remove the detail panel and restore layout."""
        if self._detail_panel is None:
            return

        if self._split_mode:
            # Restore repo list to full width
            try:
                repo_list = self.query_one("#repo-list", VerticalScroll)
                repo_list.styles.width = "1fr"
            except Exception:  # noqa: BLE001
                pass

        await self._detail_panel.remove()
        self._detail_panel = None

    # DetailPanel.Close is no longer used in modal mode (DetailScreen dismisses itself).
    # Kept as a no-op for split mode compatibility if ever needed.

    # ------------------------------------------------------------------ #
    # Group view
    # ------------------------------------------------------------------ #

    async def _toggle_group_view(self) -> None:
        self._group_view = not self._group_view
        repo_list = self.query_one("#repo-list", VerticalScroll)

        if self._group_view:
            await self._build_group_view(repo_list)
        else:
            await self._build_flat_view(repo_list)

    async def _build_flat_view(self, repo_list: VerticalScroll) -> None:
        """Remove group headers and show all repo rows in flat order."""
        # Remove all group headers
        for header in list(self._group_headers.values()):
            await header.remove()
        self._group_headers.clear()

        # Make all rows visible and re-mount in config order
        for row in list(repo_list.children):
            if isinstance(row, RepoRow):
                await row.remove()

        for repo in self._config.repos:
            row = self._rows.get(repo.key)
            if row:
                await repo_list.mount(row)
                row.display = True

        self._apply_filter_visibility()
        self._apply_sort_order(repo_list)

    async def _build_group_view(self, repo_list: VerticalScroll) -> None:
        """Organise rows under collapsible group headers."""
        # Remove all existing children from the scroll list
        for child in list(repo_list.children):
            await child.remove()

        # Determine groups in config order (preserving first-seen order)
        groups: dict[str, list[RepoConfig]] = {}
        for repo in self._config.repos:
            g = repo.group or "default"
            groups.setdefault(g, []).append(repo)

        self._group_headers.clear()

        for group_name, repos in groups.items():
            # Compute aggregate status
            statuses = [
                self._rows[r.key].run.display_status
                for r in repos
                if r.key in self._rows and self._rows[r.key].run is not None
            ]
            agg = aggregate_status(statuses) if statuses else "unknown"
            collapsed = self._group_collapsed.get(group_name, False)

            header = GroupHeader(
                group_name=group_name,
                repo_count=len(repos),
                agg_status=agg,
                expanded=not collapsed,
                id=f"group-{_safe_id(group_name)}",
            )
            self._group_headers[group_name] = header
            await repo_list.mount(header)

            for repo in repos:
                row = self._rows.get(repo.key)
                if row:
                    await repo_list.mount(row)
                    row.display = not collapsed

        self._apply_filter_visibility()

    def _update_group_headers(self) -> None:
        """Refresh group header aggregate statuses after a poll."""
        if not self._group_view:
            return
        groups: dict[str, list[str]] = {}
        for repo in self._config.repos:
            g = repo.group or "default"
            row = self._rows.get(repo.key)
            if row and row.run:
                groups.setdefault(g, []).append(row.run.display_status)

        for group_name, header in self._group_headers.items():
            statuses = groups.get(group_name, [])
            agg = aggregate_status(statuses) if statuses else "unknown"
            count = len([r for r in self._config.repos if (r.group or "default") == group_name])
            header.update_status(agg, count)

    def on_group_header_toggled(self, message: GroupHeader.Toggled) -> None:
        """Show or hide the rows belonging to the toggled group."""
        header = message.header
        group_name = header.group_name
        self._group_collapsed[group_name] = not header.expanded

        repo_list = self.query_one("#repo-list", VerticalScroll)
        # Find all rows that belong to this group and toggle their visibility
        in_group = False
        for child in repo_list.children:
            if isinstance(child, GroupHeader):
                in_group = child.group_name == group_name
            elif isinstance(child, RepoRow) and in_group:
                child.display = header.expanded

    # ------------------------------------------------------------------ #
    # Filter bar
    # ------------------------------------------------------------------ #

    def on_filter_bar_changed(self, message: FilterBar.Changed) -> None:
        self._filter_query = message.query
        self._apply_filter_visibility()

    def on_filter_bar_closed(self, _message: FilterBar.Closed) -> None:
        self._filter_query = ""
        self._apply_filter_visibility()
        # Return focus to first visible row
        widgets = self._focusable_widgets()
        if widgets:
            widgets[0].focus()

    def _apply_filter_visibility(self) -> None:
        """Show/hide rows based on current filter query."""
        query = self._filter_query
        repo_list = self.query_one("#repo-list", VerticalScroll)

        if self._group_view:
            # In group view: track which groups still have visible rows
            current_group_visible: dict[str, bool] = {}
            current_group: str | None = None

            for child in repo_list.children:
                if isinstance(child, GroupHeader):
                    current_group = child.group_name
                    current_group_visible.setdefault(current_group, False)
                elif isinstance(child, RepoRow) and current_group is not None:
                    group_collapsed = self._group_collapsed.get(current_group, False)
                    if group_collapsed:
                        child.display = False
                    else:
                        visible = matches(
                            query,
                            child.repo.alias or child.repo.repo,
                            child.repo.group or "default",
                            child.run.display_status if child.run else "",
                        )
                        child.display = visible
                        if visible:
                            current_group_visible[current_group] = True

            # Show/hide group headers based on whether any member is visible
            for child in repo_list.children:
                if isinstance(child, GroupHeader):
                    child.display = current_group_visible.get(child.group_name, False)
        else:
            for child in repo_list.children:
                if isinstance(child, RepoRow):
                    child.display = matches(
                        query,
                        child.repo.alias or child.repo.repo,
                        child.repo.group or "default",
                        child.run.display_status if child.run else "",
                    )

    # ------------------------------------------------------------------ #
    # Sort
    # ------------------------------------------------------------------ #

    async def _apply_sort(self) -> None:
        if self._group_view:
            # Sorting within group view is not supported; skip
            return
        repo_list = self.query_one("#repo-list", VerticalScroll)
        self._apply_sort_order(repo_list)

    def _apply_sort_order(self, repo_list: VerticalScroll) -> None:
        """Re-order RepoRow children of repo_list according to current sort mode."""
        rows = [c for c in repo_list.children if isinstance(c, RepoRow)]

        def sort_key(row: RepoRow) -> tuple[int, str]:
            run = row.run
            mode = self._sort_mode
            if mode == SortMode.ALIAS:
                return (0, row.repo.alias or row.repo.repo)
            if mode == SortMode.STATUS:
                # Rank by worst status first
                status = run.display_status if run else "unknown"
                rank_map = {"failure": 0, "in_progress": 1, "queued": 2, "success": 3, "unknown": 4}
                return (rank_map.get(status, 4), row.repo.alias or row.repo.repo)
            # LAST_RUN — most recent first (negate timestamp as int)
            if run:
                ref = run.updated_at or run.run_started_at or run.last_completed_updated_at
                ts = int(ref.timestamp()) if ref else 0
            else:
                ts = 0
            return (-ts, row.repo.alias or row.repo.repo)

        sorted_rows = sorted(rows, key=sort_key)
        for i, row in enumerate(sorted_rows):
            row.styles.order = i

    # ------------------------------------------------------------------ #
    # Rerun
    # ------------------------------------------------------------------ #

    async def _do_rerun(self, pending: _PendingRerun) -> None:
        """Execute the rerun API call after user confirmation."""
        client = self._client
        if client is None:
            return

        row = pending.row
        run = row.run
        if run is None:
            self.notify("No run data — cannot rerun", timeout=3)
            return

        owner = row.repo.owner
        repo = row.repo.repo
        run_id = run.run_id

        if pending.full:
            success = await client.rerun_all(owner, repo, run_id)
            label = "full rerun"
        else:
            success = await client.rerun_failed_jobs(owner, repo, run_id)
            label = "rerun of failed jobs"

        if success:
            self.notify(f"{label.capitalize()} triggered", timeout=3)
        else:
            self.notify(
                f"{label.capitalize()} failed — check PAT has actions:write scope",
                timeout=5,
                severity="error",
            )

    # ------------------------------------------------------------------ #
    # Adaptive alias column
    # ------------------------------------------------------------------ #

    def _update_alias_column_width(self) -> None:
        """Set alias column width based on the longest alias across all repos."""
        if not self._config.repos:
            return
        max_len = max(
            len(repo.alias or repo.repo) for repo in self._config.repos
        )
        # Add 2 chars padding, minimum 12, maximum 40
        width = min(max(max_len + 2, 12), 40)

        for row in self._rows.values():
            try:
                alias_label = row.query_one(".col-alias", Label)
                alias_label.styles.width = width
            except Exception:  # noqa: BLE001
                pass

    def _update_column_header(self) -> None:
        """Update the column header to match current alias width."""
        if not self._config.repos:
            return
        max_len = max(len(repo.alias or repo.repo) for repo in self._config.repos)
        width = min(max(max_len + 2, 12), 40)
        alias_col = "alias".ljust(width)
        header_text = f" {alias_col}branch           now          last build   age"
        try:
            self.query_one("#col-header", Static).update(header_text)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ #
    # Polling
    # ------------------------------------------------------------------ #

    def _start_polling(self) -> None:
        self._poll_task = asyncio.get_event_loop().create_task(self._poll_loop())

    @work(exclusive=False, thread=False)
    async def _poll_now(self) -> None:
        """Poll all repos immediately."""
        if self._client:
            await self._poll_all(self._client)

    async def _poll_loop(self) -> None:
        """Main polling loop — runs until the app exits."""
        interval = self._config.display.poll_interval
        if self._client:
            await self._poll_all(self._client)

        while True:
            if self._status_bar:
                self._status_bar.next_poll_in = interval

            await asyncio.sleep(interval)

            if self._client:
                await self._poll_all(self._client)

    async def _poll_all(self, client: GitHubClient) -> None:
        """Poll all configured repos and update rows."""
        any_error = False
        latest_rate_limit: RateLimitInfo | None = None

        tasks = [self._poll_repo(client, repo) for repo in self._config.repos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for repo, result in zip(self._config.repos, results):
            if isinstance(result, BaseException):
                logger.error("Unexpected error polling %s: %s", repo.key, result)
                any_error = True
                continue

            poll: PollResult = result  # type: ignore[assignment]
            if poll.error:
                any_error = True
            if poll.rate_limit:
                latest_rate_limit = poll.rate_limit

            row = self._rows.get(repo.key)
            if row:
                row.run = poll.run
                row.error = poll.error

                if poll.transitioned and poll.run:
                    row.highlighted = True
                    await self._handle_notification(repo, poll)

        if self._status_bar:
            self._status_bar.last_poll = datetime.now(tz=timezone.utc)
            self._status_bar.offline = any_error
            if latest_rate_limit:
                self._status_bar.rate_limit = latest_rate_limit

        # Refresh filter visibility and group headers after poll
        self._apply_filter_visibility()
        self._update_group_headers()

        client.flush()

    async def _poll_repo(self, client: GitHubClient, repo: RepoConfig) -> PollResult:
        """Poll a single repo — never raises."""
        try:
            return await client.get_latest_run(
                owner=repo.owner,
                repo=repo.repo,
                branch=repo.watch_branch or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Unhandled error polling %s: %s", repo.key, exc)
            return PollResult(
                run=None,
                rate_limit=None,
                cached=False,
                error=f"Internal error: {exc}",
                transitioned=False,
                previous_status=None,
            )

    async def _handle_notification(self, repo: RepoConfig, poll: PollResult) -> None:
        """Send TUI toast / system notification for a status transition."""
        if not poll.run:
            return

        status = poll.run.display_status
        notif_cfg = self._config.notifications

        should_notify = (
            (status == "success" and notif_cfg.on_success)
            or (status == "failure" and notif_cfg.on_failure)
            or (status == "cancelled" and notif_cfg.on_cancelled)
        )

        if not should_notify:
            return

        title = repo.alias or repo.repo
        message = f"Build {status}"
        if poll.previous_status:
            message = f"{poll.previous_status} → {status}"

        urgency = urgency_for_status(status)
        await notify(
            self,
            title=title,
            message=message,
            urgency=urgency,
            system=notif_cfg.system_notify,
        )

    # ------------------------------------------------------------------ #
    # Config file watching
    # ------------------------------------------------------------------ #

    def _start_config_watch(self) -> None:
        self._watch_task = asyncio.get_event_loop().create_task(self._watch_config())

    async def _watch_config(self) -> None:
        """Watch the config file and reload repos when it changes."""
        try:
            from watchfiles import awatch
        except ImportError:
            logger.warning("watchfiles not available — live config reload disabled")
            return

        try:
            async for _ in awatch(str(self._config_path)):
                await self._reload_config()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Config watch error: %s", exc)

    async def _reload_config(self) -> None:
        """Reload config and sync repo rows."""
        try:
            new_config = load_config(self._config_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to reload config: %s", exc)
            return

        new_keys = {r.key for r in new_config.repos}
        old_keys = set(self._rows.keys())

        repo_list = self.query_one("#repo-list", VerticalScroll)

        # Add new repos
        for repo in new_config.repos:
            if repo.key not in old_keys:
                row = RepoRow(repo, id=f"row-{_safe_id(repo.key)}")
                self._rows[repo.key] = row
                await repo_list.mount(row)
                logger.info("Added new repo row: %s", repo.key)

        # Remove deleted repos
        for key in old_keys - new_keys:
            row = self._rows.pop(key, None)
            if row:
                await row.remove()
                logger.info("Removed repo row: %s", key)

        self._config = new_config
        if self._status_bar:
            self._status_bar.repo_count = len(new_config.repos)

        self._update_alias_column_width()
        self._update_column_header()

        self.notify("Config reloaded", timeout=3)


def _safe_id(key: str) -> str:
    """Convert a repo key (owner/repo) into a valid CSS ID fragment."""
    return key.replace("/", "-").replace(".", "-")
