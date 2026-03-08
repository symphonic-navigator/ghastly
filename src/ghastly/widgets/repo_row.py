"""Repo status row widget."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from ..api import RunData
from ..config import RepoConfig


def _format_age(dt: datetime | None) -> str:
    """Format a datetime as a human-readable age string."""
    if dt is None:
        return "—"
    now = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    total_seconds = max(0, int(delta.total_seconds()))

    total_minutes, secs = divmod(total_seconds, 60)
    hours, mins = divmod(total_minutes, 60)

    if delta.days >= 1:
        return f"{delta.days}d {hours % 24:02d}:{mins:02d}"

    return f"{hours:02d}:{mins:02d}:{secs:02d} ago"


class RepoRow(Widget):
    """A single row representing one watched repository's latest run status."""

    can_focus: ClassVar[bool] = True

    DEFAULT_CSS: ClassVar[str] = """
    RepoRow {
        height: 1;
        layout: horizontal;
        background: $surface;
        padding: 0 1;
    }

    RepoRow:focus {
        background: $accent 20%;
    }

    RepoRow.highlighted {
        background: $warning 30%;
    }

    RepoRow .col-alias {
        width: 24;
        overflow: hidden hidden;
        color: $text;
    }

    RepoRow .col-branch {
        width: 16;
        overflow: hidden hidden;
        color: $text-muted;
    }

    RepoRow .col-now {
        width: 12;
        overflow: hidden hidden;
    }

    RepoRow .col-last-build {
        width: 12;
        overflow: hidden hidden;
    }

    RepoRow .col-age {
        width: 20;
        overflow: hidden hidden;
        color: $text-muted;
    }

    RepoRow .col-error {
        width: 1fr;
        overflow: hidden hidden;
        color: $warning;
    }

    RepoRow .now-running   { color: $warning; }
    RepoRow .now-queued    { color: $text-muted; }
    RepoRow .now-empty     { color: $text-muted; }

    RepoRow .build-success  { color: $success; }
    RepoRow .build-failure  { color: $error; }
    RepoRow .build-cancelled { color: $error-darken-2; }
    RepoRow .build-empty    { color: $text-muted; }
    """

    # Reactive properties updated by the polling loop
    run: reactive[RunData | None] = reactive(None)
    error: reactive[str | None] = reactive(None)
    highlighted: reactive[bool] = reactive(False)

    class Selected(Message):
        """Posted when the user presses Enter on this row."""

        def __init__(self, row: "RepoRow") -> None:
            super().__init__()
            self.row = row

    def __init__(
        self,
        repo: RepoConfig,
        run: RunData | None = None,
        error: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.repo = repo
        self.run = run
        self.error = error

    def compose(self) -> ComposeResult:
        yield Label(self._alias_text(), classes="col-alias")
        yield Label(self._branch_text(), classes="col-branch")
        now_text, now_class = self._now_text()
        yield Label(now_text, classes=f"col-now {now_class}")
        last_text, last_class = self._last_build_text()
        yield Label(last_text, classes=f"col-last-build {last_class}")
        yield Label(self._age_text(), classes="col-age")
        if self.error:
            yield Label(f"⚠ {self.error}", classes="col-error")

    # ------------------------------------------------------------------ #
    # Timer tick — update the age column every second
    # ------------------------------------------------------------------ #

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        """Called every second to refresh time-dependent labels."""
        age_label = self.query_one(".col-age", Label)
        age_label.update(self._age_text())

    # ------------------------------------------------------------------ #
    # Key handling
    # ------------------------------------------------------------------ #

    def on_key(self, event: object) -> None:
        from textual.events import Key
        if isinstance(event, Key) and event.key == "enter":
            self.post_message(self.Selected(self))

    # ------------------------------------------------------------------ #
    # Reactive watchers
    # ------------------------------------------------------------------ #

    def watch_run(self, new_run: RunData | None) -> None:  # noqa: ARG002
        self._refresh_all()

    def watch_error(self, _new: str | None) -> None:
        self._refresh_all()

    def watch_highlighted(self, highlighted: bool) -> None:
        if highlighted:
            self.add_class("highlighted")
            # Remove highlight after 2 seconds
            self.set_timer(2.0, lambda: self.remove_class("highlighted"))
        else:
            self.remove_class("highlighted")

    def _refresh_all(self) -> None:
        """Refresh all label contents after a data update."""
        try:
            self.query_one(".col-alias", Label).update(self._alias_text())
            self.query_one(".col-branch", Label).update(self._branch_text())

            now_text, now_class = self._now_text()
            now_label = self.query_one(".col-now", Label)
            now_label.update(now_text)
            for cls in list(now_label.classes):
                if cls.startswith("now-"):
                    now_label.remove_class(cls)
            now_label.add_class(now_class)

            last_text, last_class = self._last_build_text()
            last_label = self.query_one(".col-last-build", Label)
            last_label.update(last_text)
            for cls in list(last_label.classes):
                if cls.startswith("build-"):
                    last_label.remove_class(cls)
            last_label.add_class(last_class)

            self.query_one(".col-age", Label).update(self._age_text())
        except Exception:  # noqa: BLE001
            # Widget may not be mounted yet during init
            pass

    # ------------------------------------------------------------------ #
    # Text helpers
    # ------------------------------------------------------------------ #

    def _alias_text(self) -> str:
        return self.repo.alias or self.repo.repo

    def _branch_text(self) -> str:
        if self.run and self.run.head_branch:
            return self.run.head_branch
        return self.repo.watch_branch or "—"

    def _now_text(self) -> tuple[str, str]:
        """Return (label, css-class) for the "now" column."""
        if self.run is None:
            return "—", "now-empty"
        if self.run.status == "in_progress":
            return "running", "now-running"
        if self.run.status == "queued":
            return "queued", "now-queued"
        return "—", "now-empty"

    def _last_build_text(self) -> tuple[str, str]:
        """Return (label, css-class) for the "last build" column.

        When the current run is in_progress or queued, shows last_completed_status.
        When the current run is completed, shows its conclusion.
        """
        if self.run is None:
            return "—", "build-empty"

        if self.run.status in ("in_progress", "queued"):
            status = self.run.last_completed_status
        else:
            # completed — show current conclusion
            status = self.run.conclusion

        if status is None:
            return "—", "build-empty"

        class_map: dict[str, str] = {
            "success": "build-success",
            "failure": "build-failure",
            "cancelled": "build-cancelled",
        }
        return status, class_map.get(status, "build-empty")

    def _age_text(self) -> str:
        """Age of the last completed run."""
        if self.run is None:
            return "—"
        # Prefer last_completed_updated_at for in_progress/queued runs
        if self.run.status in ("in_progress", "queued"):
            ref = self.run.last_completed_updated_at
        else:
            ref = self.run.updated_at or self.run.run_started_at
        return _format_age(ref)
