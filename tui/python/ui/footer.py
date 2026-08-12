"""Footer widget — context-sensitive keybinding hints."""
from __future__ import annotations

from textual.widget import Widget


class FooterBar(Widget):
    DEFAULT_CSS = """
    FooterBar {
        height: 1;
        background: $primary-background;
        color: $text-muted;
        padding: 0 1;
    }
    """

    _mode: str = "normal"

    def _build_display(self) -> str:
        if self._mode == "running":
            return "Running..."
        if self._mode == "home":
            return "↑↓ select  Enter open  s new session  q quit"
        return "↑↓ select  Enter run  ? help  Esc back  q quit"

    def render(self) -> str:
        return self._build_display()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.refresh()
