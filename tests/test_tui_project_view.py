"""Tests for the TUI Project View — header, action panel, content, footer."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.events import (
    StateChanged, BriefReady, HealthCheck, StepProgress,
    CommandFailed, StatusReady, WhatNextReady, Recommendation,
)


# ---------------------------------------------------------------------------
# HeaderBar unit tests
# ---------------------------------------------------------------------------

class TestHeaderBar:
    def test_renders_branch_and_state(self):
        from tui.python.ui.header import HeaderBar
        widget = HeaderBar()
        widget._branch = "issue-42-fix"
        widget._state = "active"
        widget._queue_position = ""
        text = widget._build_display()
        assert "issue-42-fix" in text
        assert "active" in text

    def test_renders_queue_position(self):
        from tui.python.ui.header import HeaderBar
        widget = HeaderBar()
        widget._branch = "issue-42"
        widget._state = "active"
        widget._queue_position = "1/3"
        text = widget._build_display()
        assert "1/3" in text

    def test_main_branch_shown(self):
        from tui.python.ui.header import HeaderBar
        widget = HeaderBar()
        widget._branch = "main"
        widget._state = "idle"
        widget._queue_position = ""
        text = widget._build_display()
        assert "main" in text
        assert "idle" in text


# ---------------------------------------------------------------------------
# ActionPanel unit tests
# ---------------------------------------------------------------------------

class TestActionPanel:
    def test_action_list_rendering(self):
        from tui.python.ui.action_panel import ActionPanel
        panel = ActionPanel()
        panel._actions = ["start", "what-next", "status"]
        panel._suggested = "start"
        panel._selected_index = 0
        text = panel._build_display()
        assert "start" in text
        assert "what-next" in text
        assert "status" in text

    def test_selected_index_highlighted(self):
        from tui.python.ui.action_panel import ActionPanel
        panel = ActionPanel()
        panel._actions = ["start", "what-next", "status"]
        panel._suggested = "start"
        panel._selected_index = 1
        text = panel._build_display()
        lines = [l for l in text.splitlines() if l.strip()]
        action_lines = [l for l in lines if "what-next" in l]
        assert any(">" in l or "▸" in l for l in action_lines)

    def test_move_down(self):
        from tui.python.ui.action_panel import ActionPanel
        panel = ActionPanel()
        panel._actions = ["start", "what-next", "status"]
        panel._selected_index = 0
        panel._enabled = True
        panel.move_down()
        assert panel._selected_index == 1

    def test_move_up(self):
        from tui.python.ui.action_panel import ActionPanel
        panel = ActionPanel()
        panel._actions = ["start", "what-next", "status"]
        panel._selected_index = 2
        panel._enabled = True
        panel.move_up()
        assert panel._selected_index == 1

    def test_move_down_clamped(self):
        from tui.python.ui.action_panel import ActionPanel
        panel = ActionPanel()
        panel._actions = ["start", "status"]
        panel._selected_index = 1
        panel._enabled = True
        panel.move_down()
        assert panel._selected_index == 1

    def test_move_up_clamped(self):
        from tui.python.ui.action_panel import ActionPanel
        panel = ActionPanel()
        panel._actions = ["start", "status"]
        panel._selected_index = 0
        panel._enabled = True
        panel.move_up()
        assert panel._selected_index == 0

    def test_disabled_blocks_movement(self):
        from tui.python.ui.action_panel import ActionPanel
        panel = ActionPanel()
        panel._actions = ["start", "status"]
        panel._selected_index = 0
        panel._enabled = False
        panel.move_down()
        assert panel._selected_index == 0

    def test_suggested_action_marked(self):
        from tui.python.ui.action_panel import ActionPanel
        panel = ActionPanel()
        panel._actions = ["start", "what-next", "status"]
        panel._suggested = "start"
        panel._selected_index = 0
        text = panel._build_display()
        lines = text.splitlines()
        start_line = [l for l in lines if "start" in l][0]
        assert "★" in start_line or "*" in start_line


# ---------------------------------------------------------------------------
# ContentArea unit tests
# ---------------------------------------------------------------------------

class TestContentArea:
    def test_format_brief(self):
        from tui.python.ui.content import ContentArea
        area = ContentArea()
        brief = BriefReady(
            issue=42, branch="issue-42", state="active",
            queue_position="1/3",
            health=[
                HealthCheck("meta_consistency", "ok", None),
                HealthCheck("pause_stack", "warn", "2 stale entries"),
            ],
            is_epic=False, epic_batch=None, epic_active_issue=None,
        )
        lines = area.format_brief(brief)
        text = "\n".join(lines)
        assert "#42" in text
        assert "issue-42" in text
        assert "1/3" in text
        assert "meta_consistency" in text
        assert "2 stale entries" in text

    def test_format_step_progress(self):
        from tui.python.ui.content import ContentArea
        area = ContentArea()
        step = StepProgress("end", "rebased", None)
        line = area.format_step_progress(step)
        assert "rebased" in line

    def test_format_step_progress_with_detail(self):
        from tui.python.ui.content import ContentArea
        area = ContentArea()
        step = StepProgress("end", "pushing", "attempt 2/3")
        line = area.format_step_progress(step)
        assert "pushing" in line
        assert "attempt 2/3" in line

    def test_format_error(self):
        from tui.python.ui.content import ContentArea
        area = ContentArea()
        failed = CommandFailed("end", "rebasing", "rebase_failed",
                               "Conflicts in file.py", True)
        lines = area.format_error(failed)
        text = "\n".join(lines)
        assert "end" in text
        assert "rebasing" in text
        assert "Conflicts in file.py" in text

    def test_format_error_recoverable_shown(self):
        from tui.python.ui.content import ContentArea
        area = ContentArea()
        failed = CommandFailed("end", None, "push_failed",
                               "Rejected by remote", True)
        lines = area.format_error(failed)
        text = "\n".join(lines)
        assert "retry" in text.lower() or "recoverable" in text.lower()

    def test_format_status(self):
        from tui.python.ui.content import ContentArea
        area = ContentArea()
        status = StatusReady(
            branch="issue-42", state="active", on_main=False,
            in_slot=True, has_plan=True, plan_position="1/3",
            stack_depth=0, owner_repo="Hortora/soredium",
            base_branch="main",
        )
        lines = area.format_status(status)
        text = "\n".join(lines)
        assert "issue-42" in text
        assert "active" in text

    def test_format_what_next(self):
        from tui.python.ui.content import ContentArea
        area = ContentArea()
        wn = WhatNextReady(recommendations=[
            Recommendation(55, "Refactor auth", "quick-win", "ready", "Low risk"),
            Recommendation(99, "Add tests", None, None, None),
        ])
        lines = area.format_what_next(wn)
        text = "\n".join(lines)
        assert "#55" in text
        assert "Refactor auth" in text
        assert "#99" in text


# ---------------------------------------------------------------------------
# FooterBar unit tests
# ---------------------------------------------------------------------------

class TestFooterBar:
    def test_normal_mode(self):
        from tui.python.ui.footer import FooterBar
        bar = FooterBar()
        bar._mode = "normal"
        text = bar._build_display()
        assert "Enter" in text
        assert "q" in text

    def test_running_mode(self):
        from tui.python.ui.footer import FooterBar
        bar = FooterBar()
        bar._mode = "running"
        text = bar._build_display()
        assert "Running" in text

    def test_home_mode(self):
        from tui.python.ui.footer import FooterBar
        bar = FooterBar()
        bar._mode = "home"
        text = bar._build_display()
        assert "Enter" in text


# ---------------------------------------------------------------------------
# Integration: action derivation drives panel content
# ---------------------------------------------------------------------------

class TestActionDerivationIntegration:
    def test_state_changed_updates_panel(self):
        from tui.python.ui.action_panel import ActionPanel
        panel = ActionPanel()
        state = StateChanged("idle", "active",
                              ["continue", "brief", "next", "pause", "end", "session", "status"],
                              "next")
        panel.apply_state(state)
        assert panel._actions == ["continue", "brief", "next", "pause", "end", "session", "status"]
        assert panel._suggested == "next"
        assert panel._selected_index == 0

    def test_idle_state_actions(self):
        from commands.registry import derive_actions
        from tui.python.ui.action_panel import ActionPanel
        actions, suggested = derive_actions("idle", stack_depth=0)
        panel = ActionPanel()
        panel.apply_state(StateChanged("idle", "idle", actions, suggested))
        assert "start" in panel._actions
        assert "resume" not in panel._actions

    def test_idle_with_stack_shows_resume(self):
        from commands.registry import derive_actions
        from tui.python.ui.action_panel import ActionPanel
        actions, suggested = derive_actions("idle", stack_depth=2)
        panel = ActionPanel()
        panel.apply_state(StateChanged("idle", "idle", actions, suggested))
        assert "resume" in panel._actions
        assert panel._suggested == "resume"
