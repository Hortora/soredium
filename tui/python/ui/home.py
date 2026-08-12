"""Home View widget — repo/slot list with session status."""
from __future__ import annotations

from textual.widget import Widget
from textual.message import Message

from commands.events import RepoSlotInfo, HomeReady


class RepoSelected(Message):
    def __init__(self, info: RepoSlotInfo) -> None:
        self.info = info
        super().__init__()


class HomeView(Widget):
    DEFAULT_CSS = """
    HomeView {
        padding: 1;
    }
    """

    can_focus = True

    BINDINGS = [
        ("up", "move_up", "Up"),
        ("down", "move_down", "Down"),
        ("enter", "select_repo", "Select"),
    ]

    _repos: list[RepoSlotInfo] = []
    _selected_index: int = 0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._repos = []
        self._selected_index = 0

    def _build_display(self) -> str:
        lines = ["Repos & Slots", ""]
        if not self._repos:
            lines.append("  No repos found. Configure scan_paths in ~/.soredium/config.toml")
            lines.append("")
            lines.append("● running  ◐ paused  ○ idle")
            return "\n".join(lines)

        for i, repo in enumerate(self._repos):
            cursor = "▸ " if i == self._selected_index else "  "
            slot_str = f"  {repo.slot}" if repo.slot else ""
            branch_str = f"[{repo.branch}]"

            if repo.tmux_session:
                indicator = "●"
            elif repo.state == "paused":
                indicator = "◐"
            else:
                indicator = "○"

            line = f"{cursor}{repo.repo}{slot_str}  {branch_str} {repo.state}  {indicator}"
            lines.append(line)

        lines.append("")
        lines.append("● running  ◐ paused  ○ idle")
        return "\n".join(lines)

    def render(self) -> str:
        return self._build_display()

    def move_down(self) -> None:
        if self._repos and self._selected_index < len(self._repos) - 1:
            self._selected_index += 1
            self.refresh()

    def move_up(self) -> None:
        if self._repos and self._selected_index > 0:
            self._selected_index -= 1
            self.refresh()

    def action_move_down(self) -> None:
        self.move_down()

    def action_move_up(self) -> None:
        self.move_up()

    def action_select_repo(self) -> None:
        if self._repos:
            self.post_message(RepoSelected(self._repos[self._selected_index]))

    def apply_home_ready(self, home: HomeReady) -> None:
        self._repos = list(home.repos)
        self._selected_index = 0
        self.refresh()
