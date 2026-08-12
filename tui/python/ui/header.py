"""Header widget — branch, lifecycle state, queue position."""
from __future__ import annotations

from textual.widget import Widget
from textual.reactive import reactive


class HeaderBar(Widget):
    DEFAULT_CSS = """
    HeaderBar {
        height: 3;
        padding: 0 1;
        background: $primary-background;
        color: $text;
    }
    """

    _branch: str = "main"
    _state: str = "idle"
    _queue_position: str = ""

    def _build_display(self) -> str:
        parts = ["soredium"]
        parts.append(f"[{self._branch}]")
        parts.append(self._state)
        if self._queue_position:
            parts.append(f"Queue: {self._queue_position}")
        return "   ".join(parts)

    def render(self) -> str:
        return self._build_display()

    def update_from_context(self, branch: str, state: str,
                            queue_position: str) -> None:
        self._branch = branch
        self._state = state
        self._queue_position = queue_position
        self.refresh()
