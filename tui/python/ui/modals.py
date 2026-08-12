"""Input modals — overlays for issue numbers, messages, branch selection."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option


class InputModal(ModalScreen[str | None]):
    """Single-line text input modal."""

    DEFAULT_CSS = """
    InputModal {
        align: center middle;
    }
    InputModal > Vertical {
        width: 50;
        height: auto;
        max-height: 10;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, prompt: str, placeholder: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._prompt)
            yield Input(placeholder=self._placeholder)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value if value else None)

    def key_escape(self) -> None:
        self.dismiss(None)


class BranchPickerModal(ModalScreen[str | None]):
    """Branch selection modal for resume with multiple paused branches."""

    DEFAULT_CSS = """
    BranchPickerModal {
        align: center middle;
    }
    BranchPickerModal > Vertical {
        width: 60;
        height: auto;
        max-height: 20;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, branches: list[tuple[str, str]]) -> None:
        super().__init__()
        self._branches = branches

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Select branch to resume:")
            option_list = OptionList()
            for branch, detail in self._branches:
                option_list.add_option(Option(f"{branch}  {detail}"))
            yield option_list

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        idx = event.option_index
        if 0 <= idx < len(self._branches):
            self.dismiss(self._branches[idx][0])

    def key_escape(self) -> None:
        self.dismiss(None)
