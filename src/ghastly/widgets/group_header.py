"""Group header widget for the grouped repo view."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


# Aggregate status ordering: higher index = worse
_STATUS_RANK: dict[str, int] = {
    "success": 0,
    "queued": 1,
    "in_progress": 2,
    "failure": 3,
    "cancelled": 3,
}


def aggregate_status(statuses: list[str]) -> str:
    """Return the worst status from a list of display_status strings."""
    if not statuses:
        return "unknown"
    return max(statuses, key=lambda s: _STATUS_RANK.get(s, 0))


class GroupHeader(Widget):
    """Collapsible group header row shown in group view.

    Displays: ▶/▼ group-name  [N repos]  aggregate-status
    """

    can_focus: ClassVar[bool] = True

    DEFAULT_CSS: ClassVar[str] = """
    GroupHeader {
        height: 1;
        layout: horizontal;
        background: $surface-darken-1;
        padding: 0 1;
    }

    GroupHeader:focus {
        background: $accent 20%;
    }

    GroupHeader #gh-label {
        width: 1fr;
        color: $text;
        text-style: bold;
    }

    GroupHeader #gh-status {
        width: 12;
        text-align: right;
    }

    GroupHeader .status-success   { color: $success; }
    GroupHeader .status-failure   { color: $error; }
    GroupHeader .status-cancelled { color: $error-darken-2; }
    GroupHeader .status-in_progress { color: $warning; }
    GroupHeader .status-queued    { color: $text-muted; }
    GroupHeader .status-unknown   { color: $text-muted; }
    """

    expanded: reactive[bool] = reactive(True)

    class Toggled(Message):
        """Posted when the header is toggled (expand/collapse)."""

        def __init__(self, header: "GroupHeader") -> None:
            super().__init__()
            self.header = header

    def __init__(
        self,
        group_name: str,
        repo_count: int,
        agg_status: str,
        expanded: bool = True,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.group_name = group_name
        self.repo_count = repo_count
        self.agg_status = agg_status
        self.expanded = expanded

    def compose(self) -> ComposeResult:
        arrow = "▼" if self.expanded else "▶"
        label_text = f"{arrow} {self.group_name}  [{self.repo_count} repos]"
        yield Label(label_text, id="gh-label")
        status_class = f"status-{self.agg_status}"
        yield Label(self.agg_status, id="gh-status", classes=status_class)

    def watch_expanded(self, expanded: bool) -> None:
        self._refresh_label()

    def _refresh_label(self) -> None:
        try:
            arrow = "▼" if self.expanded else "▶"
            label_text = f"{arrow} {self.group_name}  [{self.repo_count} repos]"
            self.query_one("#gh-label", Label).update(label_text)
        except Exception:  # noqa: BLE001
            pass

    def update_status(self, agg_status: str, repo_count: int) -> None:
        """Update aggregate status and repo count after polling."""
        self.agg_status = agg_status
        self.repo_count = repo_count
        self._refresh_label()
        try:
            status_label = self.query_one("#gh-status", Label)
            status_label.update(agg_status)
            # Clear old status classes and apply new one
            for cls in list(status_label.classes):
                if cls.startswith("status-"):
                    status_label.remove_class(cls)
            status_label.add_class(f"status-{agg_status}")
        except Exception:  # noqa: BLE001
            pass

    def toggle(self) -> None:
        """Toggle expanded/collapsed state."""
        self.expanded = not self.expanded
        self.post_message(self.Toggled(self))

    def on_key(self, event: object) -> None:
        from textual.events import Key
        if isinstance(event, Key) and event.key in ("enter", "l", "right"):
            if not self.expanded:
                self.toggle()
        elif isinstance(event, Key) and event.key in ("h", "left"):
            if self.expanded:
                self.toggle()
