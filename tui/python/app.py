"""Soredium TUI — Textual app for lifecycle operations."""
from __future__ import annotations

import importlib
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.worker import Worker, WorkerState

from tui.python.ui.header import HeaderBar
from tui.python.ui.action_panel import ActionPanel, ActionSelected
from tui.python.ui.content import ContentArea
from tui.python.ui.footer import FooterBar
from tui.python.ui.home import HomeView, RepoSelected
from tui.python.ui.modals import InputModal
from commands import events
from commands.registry import resolve_context, refresh, derive_actions


class SorediumApp(App):
    CSS_PATH = "styles/app.tcss"
    TITLE = "soredium"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "back", "Back"),
    ]

    def __init__(self, cwd: str | None = None,
                 scan_paths: list[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cwd = cwd
        self.scan_paths = scan_paths or ["~/claude/"]
        self._running_command = False
        self._view = "project" if cwd else "home"

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Horizontal(id="main-container"):
            if self._view == "home":
                yield HomeView()
            else:
                yield ActionPanel()
            yield ContentArea()
        yield FooterBar()

    def on_mount(self) -> None:
        if self._view == "home":
            self._load_home()
        else:
            self._refresh_state()
            self.query_one(ActionPanel).focus()

    def _load_home(self) -> None:
        header = self.query_one(HeaderBar)
        header.update_from_context("", "home", "")
        footer = self.query_one(FooterBar)
        footer.set_mode("home")

        try:
            from commands.discover import discover_repos
            home_ready = discover_repos(self.scan_paths)
            home_view = self.query_one(HomeView)
            home_view.apply_home_ready(home_ready)
            home_view.focus()
        except Exception as e:
            content = self.query_one(ContentArea)
            content.clear()
            content.write(f"Discovery failed: {e}")

    def _switch_to_project(self, info: events.RepoSlotInfo) -> None:
        self.cwd = info.project_path
        self._view = "project"

        container = self.query_one("#main-container")
        home_view = self.query_one(HomeView)
        home_view.remove()

        panel = ActionPanel()
        container.mount(panel, before=self.query_one(ContentArea))

        self._refresh_state()
        panel.focus()
        self.query_one(FooterBar).set_mode("normal")

    def _switch_to_home(self) -> None:
        if self._view == "home" or self._running_command:
            return
        self._view = "home"
        self.cwd = None

        container = self.query_one("#main-container")
        panel = self.query_one(ActionPanel)
        panel.remove()

        home_view = HomeView()
        container.mount(home_view, before=self.query_one(ContentArea))

        content = self.query_one(ContentArea)
        content.clear()

        self._load_home()

    def action_back(self) -> None:
        if self._view == "project" and not self._running_command:
            self._switch_to_home()

    def on_repo_selected(self, message: RepoSelected) -> None:
        self._switch_to_project(message.info)

    # ----- Project View -----

    def _refresh_state(self) -> None:
        try:
            state = refresh(self.cwd)
            self._apply_state(state)
        except Exception as e:
            content = self.query_one(ContentArea)
            content.clear()
            content.write(f"Failed to detect state: {e}")

    def _apply_state(self, state: events.StateChanged) -> None:
        header = self.query_one(HeaderBar)
        panel = self.query_one(ActionPanel)

        try:
            ctx = resolve_context(self.cwd)
            header.update_from_context(
                ctx.branch, state.new_state,
                ctx.plan_position or "",
            )
        except Exception:
            header.update_from_context("?", state.new_state, "")

        panel.apply_state(state)

    def on_action_selected(self, message: ActionSelected) -> None:
        if not self._running_command:
            self._handle_action(message.action)

    def _handle_action(self, action: str) -> None:
        if action == "start":
            self.push_screen(
                InputModal("Issue numbers (space-separated):", "#42 #43"),
                callback=self._on_start_input,
            )
        elif action == "quick-fix":
            self.push_screen(
                InputModal("Commit message:", "fix: ..."),
                callback=self._on_quickfix_input,
            )
        else:
            self._run_command(action)

    def _on_start_input(self, value: str | None) -> None:
        if value:
            nums = []
            for part in value.split():
                cleaned = part.lstrip("#")
                if cleaned.isdigit():
                    nums.append(int(cleaned))
            if nums:
                self._run_command("start", issues=nums)

    def _on_quickfix_input(self, value: str | None) -> None:
        if value:
            self._run_command("quick-fix", message=value)

    def _run_command(self, action: str, **extra_kwargs) -> None:
        self._running_command = True
        panel = self.query_one(ActionPanel)
        panel.set_enabled(False)
        footer = self.query_one(FooterBar)
        footer.set_mode("running")
        content = self.query_one(ContentArea)
        content.clear()
        content.write(f"Running {action}...")
        content.write("")

        self.run_worker(
            self._execute_command(action, **extra_kwargs),
            exclusive=True,
            thread=True,
        )

    async def _execute_command(self, action: str, **extra_kwargs) -> None:
        content = self.query_one(ContentArea)
        try:
            cmd_name = action.replace("-", "_")
            mod = importlib.import_module(f"commands.{cmd_name}")
            kwargs = {"cwd": self.cwd, **extra_kwargs}
            result = mod.execute(**kwargs)

            if isinstance(result, list):
                for event in result:
                    self._handle_event(event)
            else:
                self._handle_event(result)

        except Exception as e:
            failed = events.CommandFailed(action, None, "exception", str(e), False)
            for line in content.format_error(failed):
                content.write(line)
        finally:
            self._running_command = False
            self.query_one(ActionPanel).set_enabled(True)
            self.query_one(FooterBar).set_mode("normal")

    def _handle_event(self, event) -> None:
        content = self.query_one(ContentArea)

        if isinstance(event, events.StateChanged):
            self._apply_state(event)
        elif isinstance(event, events.StepProgress):
            content.write(content.format_step_progress(event))
        elif isinstance(event, events.CommandFailed):
            for line in content.format_error(event):
                content.write(line)
        else:
            content.show_event(event)
