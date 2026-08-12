"""Action panel — context-sensitive action list with keyboard navigation."""
from __future__ import annotations

from textual.widget import Widget
from textual.message import Message

from commands.events import StateChanged


class ActionSelected(Message):
    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__()


class ActionPanel(Widget):
    DEFAULT_CSS = """
    ActionPanel {
        width: 22;
        border-right: solid $primary;
        padding: 1;
    }
    ActionPanel:focus {
        border-right: solid $accent;
    }
    """

    can_focus = True

    BINDINGS = [
        ("up", "move_up", "Up"),
        ("down", "move_down", "Down"),
        ("enter", "select_action", "Select"),
    ]

    _actions: list[str] = []
    _suggested: str = ""
    _selected_index: int = 0
    _enabled: bool = True

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._actions = []
        self._suggested = ""
        self._selected_index = 0
        self._enabled = True

    def _build_display(self) -> str:
        lines = ["Actions", ""]
        for i, action in enumerate(self._actions):
            cursor = "▸ " if i == self._selected_index else "  "
            star = " ★" if action == self._suggested else ""
            lines.append(f"{cursor}{action}{star}")
        return "\n".join(lines)

    def render(self) -> str:
        return self._build_display()

    def move_down(self) -> None:
        if self._enabled and self._selected_index < len(self._actions) - 1:
            self._selected_index += 1
            self.refresh()

    def move_up(self) -> None:
        if self._enabled and self._selected_index > 0:
            self._selected_index -= 1
            self.refresh()

    def select_current(self) -> str | None:
        if self._enabled and self._actions:
            action = self._actions[self._selected_index]
            self.post_message(ActionSelected(action))
            return action
        return None

    def apply_state(self, state: StateChanged) -> None:
        self._actions = list(state.available_actions)
        self._suggested = state.suggested_action or ""
        self._selected_index = 0
        self._enabled = True
        self.refresh()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.refresh()

    def action_move_down(self) -> None:
        self.move_down()

    def action_move_up(self) -> None:
        self.move_up()

    def action_select_action(self) -> None:
        self.select_current()
