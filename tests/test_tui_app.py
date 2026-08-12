"""Integration tests for the Textual TUI app using Textual's test framework."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.events import StateChanged, BriefReady, HealthCheck
from commands.registry import Context


def _mock_context(**overrides) -> Context:
    defaults = dict(
        project_path="/tmp/test-project",
        workspace_path="/tmp/test-workspace",
        branch="issue-42-fix",
        state="active",
        on_main=False,
        in_slot=False,
        has_plan=True,
        plan_position="1/3",
        stack_depth=0,
        owner_repo="Test/repo",
        base_branch="main",
        meta_path="/tmp/test-workspace/design/.meta",
        has_queue=True,
        issue=42,
        is_epic=False,
        epic_batch=None,
        epic_active_issue=None,
    )
    defaults.update(overrides)
    return Context(**defaults)


def _mock_refresh(cwd=None):
    return StateChanged(
        "idle", "active",
        ["continue", "brief", "next", "pause", "end", "session", "status"],
        "next",
    )


def _mock_resolve_context(cwd=None):
    return _mock_context()


# ---------------------------------------------------------------------------
# App composition tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_app_composes_all_widgets():
    with patch("tui.python.app.refresh", side_effect=_mock_refresh), \
         patch("tui.python.app.resolve_context", side_effect=_mock_resolve_context):
        from tui.python.app import SorediumApp
        from tui.python.ui.header import HeaderBar
        from tui.python.ui.action_panel import ActionPanel
        from tui.python.ui.content import ContentArea
        from tui.python.ui.footer import FooterBar

        app = SorediumApp(cwd="/tmp/test")
        async with app.run_test() as pilot:
            assert pilot.app.query_one(HeaderBar) is not None
            assert pilot.app.query_one(ActionPanel) is not None
            assert pilot.app.query_one(ContentArea) is not None
            assert pilot.app.query_one(FooterBar) is not None


@pytest.mark.asyncio
async def test_app_initializes_with_state():
    with patch("tui.python.app.refresh", side_effect=_mock_refresh), \
         patch("tui.python.app.resolve_context", side_effect=_mock_resolve_context):
        from tui.python.app import SorediumApp
        from tui.python.ui.action_panel import ActionPanel

        app = SorediumApp(cwd="/tmp/test")
        async with app.run_test() as pilot:
            panel = pilot.app.query_one(ActionPanel)
            assert "continue" in panel._actions
            assert "next" in panel._actions
            assert panel._suggested == "next"


@pytest.mark.asyncio
async def test_keyboard_navigation():
    with patch("tui.python.app.refresh", side_effect=_mock_refresh), \
         patch("tui.python.app.resolve_context", side_effect=_mock_resolve_context):
        from tui.python.app import SorediumApp
        from tui.python.ui.action_panel import ActionPanel

        app = SorediumApp(cwd="/tmp/test")
        async with app.run_test() as pilot:
            panel = pilot.app.query_one(ActionPanel)
            panel.focus()
            await pilot.pause()
            assert panel._selected_index == 0
            await pilot.press("down")
            assert panel._selected_index == 1
            await pilot.press("down")
            assert panel._selected_index == 2
            await pilot.press("up")
            assert panel._selected_index == 1


@pytest.mark.asyncio
async def test_app_quit():
    with patch("tui.python.app.refresh", side_effect=_mock_refresh), \
         patch("tui.python.app.resolve_context", side_effect=_mock_resolve_context):
        from tui.python.app import SorediumApp

        app = SorediumApp(cwd="/tmp/test")
        async with app.run_test() as pilot:
            await pilot.press("q")
            assert app.return_code is not None or not app.is_running


# ---------------------------------------------------------------------------
# Modal tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_input_modal_dismiss_on_escape():
    from tui.python.ui.modals import InputModal

    result = None

    def capture(value):
        nonlocal result
        result = value

    from tui.python.app import SorediumApp
    with patch("tui.python.app.refresh", side_effect=_mock_refresh), \
         patch("tui.python.app.resolve_context", side_effect=_mock_resolve_context):
        app = SorediumApp(cwd="/tmp/test")
        async with app.run_test() as pilot:
            app.push_screen(InputModal("Test:", "hint"), callback=capture)
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert result is None
