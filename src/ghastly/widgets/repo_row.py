"""Repo status row widget."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from ..api import RunData
from ..config import RepoConfig


def _format_duration(seconds: int) -> str:
    """Format a duration in seconds as m:ss or h:mm:ss."""
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def _format_age(dt: datetime | None) -> str:
    """Format a datetime as a human-readable age string."""
    if dt is None:
        return "—"
    now = datetime.now(tz=UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
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
        background: $accent 40%;
    }

    RepoRow.highlighted {
        background: $warning 30%;
    }

    RepoRow .col-alias {
        min-width: 8;
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

    RepoRow .col-duration {
        width: 8;
        overflow: hidden hidden;
        color: $text-muted;
    }

    RepoRow .col-duration.duration-running {
        color: $warning;
    }

    RepoRow .col-age {
        width: 20;
        overflow: hidden hidden;
        color: $text-muted;
    }

    RepoRow .col-commit {
        width: 1fr;
        overflow: hidden hidden;
    }

    RepoRow .commit-normal { color: $text-muted; }
    RepoRow .commit-error  { color: $warning; }

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

        def __init__(self, row: RepoRow) -> None:
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
        dur_text, dur_class = self._duration_text()
        yield Label(dur_text, classes=f"col-duration {dur_class}")
        yield Label(self._age_text(), classes="col-age")
        commit_class = "commit-error" if self.error else "commit-normal"
        yield Label(self._commit_text(), classes=f"col-commit {commit_class}")

    # ------------------------------------------------------------------ #
    # Timer tick — update the age column every second
    # ------------------------------------------------------------------ #

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        """Called every second to refresh time-dependent labels."""
        self.query_one(".col-age", Label).update(self._age_text())
        if self.run and self.run.status == "in_progress":
            dur_text, dur_class = self._duration_text()
            dur_label = self.query_one(".col-duration", Label)
            dur_label.update(dur_text)
            dur_label.set_class(dur_class == "duration-running", "duration-running")

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
            dur_text, dur_class = self._duration_text()
            dur_label = self.query_one(".col-duration", Label)
            dur_label.update(dur_text)
            dur_label.set_class(dur_class == "duration-running", "duration-running")
            commit_label = self.query_one(".col-commit", Label)
            commit_label.update(self._commit_text())
            commit_label.set_class(bool(self.error), "commit-error")
            commit_label.set_class(not bool(self.error), "commit-normal")
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

    def _commit_text(self) -> str:
        if self.error:
            return f"⚠ {self.error}"
        if self.run and self.run.head_commit_message:
            msg = self.run.head_commit_message.replace("\n", " ").replace("\r", "").strip()
            if len(msg) > 90:
                msg = msg[:87] + "…"
            return msg
        return ""

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

    def _duration_text(self) -> tuple[str, str]:
        """Return (label, css-class) for the duration column.

        In-progress: live elapsed time since run_started_at (updates every tick).
        Completed: static duration = updated_at − run_started_at.
        """
        if self.run is None:
            return "—", ""
        start = self.run.run_started_at
        if start is None:
            return "—", ""
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)

        if self.run.status == "in_progress":
            elapsed = max(0, int((datetime.now(tz=UTC) - start).total_seconds()))
            return _format_duration(elapsed), "duration-running"

        if self.run.status == "completed" and self.run.updated_at:
            end = self.run.updated_at
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            secs = max(0, int((end - start).total_seconds()))
            return _format_duration(secs), ""

        return "—", ""
