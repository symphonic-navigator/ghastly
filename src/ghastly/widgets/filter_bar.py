"""Live fuzzy filter bar widget."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input


def _score(query: str, text: str) -> int:
    """Simple substring score: match position bonus + consecutive bonus.

    Returns 0 if no match, positive score otherwise (higher = better match).
    """
    if not query:
        return 1  # Empty query matches everything
    q = query.lower()
    t = text.lower()
    pos = t.find(q)
    if pos == -1:
        return 0
    # Earlier match = higher score; length-based bonus for longer matches
    position_score = max(1, 100 - pos)
    consecutive_bonus = len(q) * 2
    return position_score + consecutive_bonus


def matches(query: str, alias: str, group: str, status: str) -> bool:
    """Return True if query matches any of the given fields."""
    if not query:
        return True
    return (
        _score(query, alias) > 0
        or _score(query, group) > 0
        or _score(query, status) > 0
    )


class FilterBar(Widget):
    """Live filter bar — opens at the bottom of the screen when / is pressed.

    Posts FilterBar.Changed when the query changes, and FilterBar.Closed on Esc.
    """

    DEFAULT_CSS: ClassVar[str] = """
    FilterBar {
        height: 1;
        layout: horizontal;
        background: $surface-darken-1;
        display: none;
    }

    FilterBar.visible {
        display: block;
    }

    FilterBar Input {
        height: 1;
        border: none;
        background: $surface-darken-1;
        padding: 0 1;
        width: 1fr;
    }

    FilterBar Input:focus {
        border: none;
    }
    """

    query: reactive[str] = reactive("")

    class Changed(Message):
        """Posted whenever the filter query changes."""

        def __init__(self, query: str) -> None:
            super().__init__()
            self.query = query

    class Closed(Message):
        """Posted when the filter bar is dismissed (Esc)."""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="filter…", id="filter-input")

    def open(self) -> None:
        """Show the filter bar and focus the input."""
        self.add_class("visible")
        try:
            inp = self.query_one("#filter-input", Input)
            inp.value = ""
            self.query = ""
            inp.focus()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        """Clear and hide the filter bar."""
        self.remove_class("visible")
        self.query = ""
        try:
            self.query_one("#filter-input", Input).value = ""
        except Exception:  # noqa: BLE001
            pass
        self.post_message(self.Closed())

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query = event.value
        self.post_message(self.Changed(event.value))
        event.stop()

    def on_key(self, event: object) -> None:
        from textual.events import Key
        if isinstance(event, Key) and event.key == "escape":
            self.close()
