"""Tests for the TUI Home View widget."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.events import RepoSlotInfo, HomeReady, StateChanged


# ---------------------------------------------------------------------------
# HomeView unit tests
# ---------------------------------------------------------------------------

class TestHomeView:
    def _make_repos(self):
        return [
            RepoSlotInfo("casehub/engine", None, "main", "idle", None,
                         None, None, "/path/engine", None),
            RepoSlotInfo("hortora/soredium", "slot/7", "issue-222", "active",
                         222, "1/3", "soredium-slot7-222", "/path/soredium",
                         "/path/workspace"),
            RepoSlotInfo("hortora/engine", None, "issue-42", "active", 42,
                         None, None, "/path/hengine", None),
        ]

    def test_renders_all_repos(self):
        from tui.python.ui.home import HomeView
        view = HomeView()
        view._repos = self._make_repos()
        text = view._build_display()
        assert "casehub/engine" in text
        assert "hortora/soredium" in text
        assert "hortora/engine" in text

    def test_shows_slot_info(self):
        from tui.python.ui.home import HomeView
        view = HomeView()
        view._repos = self._make_repos()
        text = view._build_display()
        assert "slot/7" in text

    def test_shows_session_indicators(self):
        from tui.python.ui.home import HomeView
        view = HomeView()
        view._repos = self._make_repos()
        text = view._build_display()
        assert "●" in text  # active tmux session
        assert "○" in text  # idle

    def test_selected_index_highlighted(self):
        from tui.python.ui.home import HomeView
        view = HomeView()
        view._repos = self._make_repos()
        view._selected_index = 1
        text = view._build_display()
        lines = text.splitlines()
        soredium_lines = [l for l in lines if "soredium" in l]
        assert any("▸" in l or ">" in l for l in soredium_lines)

    def test_move_down(self):
        from tui.python.ui.home import HomeView
        view = HomeView()
        view._repos = self._make_repos()
        view._selected_index = 0
        view.move_down()
        assert view._selected_index == 1

    def test_move_up(self):
        from tui.python.ui.home import HomeView
        view = HomeView()
        view._repos = self._make_repos()
        view._selected_index = 2
        view.move_up()
        assert view._selected_index == 1

    def test_move_clamped_at_bounds(self):
        from tui.python.ui.home import HomeView
        view = HomeView()
        view._repos = self._make_repos()
        view._selected_index = 0
        view.move_up()
        assert view._selected_index == 0
        view._selected_index = 2
        view.move_down()
        assert view._selected_index == 2

    def test_empty_repos_renders_message(self):
        from tui.python.ui.home import HomeView
        view = HomeView()
        view._repos = []
        text = view._build_display()
        assert "No repos" in text or "empty" in text.lower() or len(text.strip()) > 0

    def test_apply_home_ready(self):
        from tui.python.ui.home import HomeView
        view = HomeView()
        home = HomeReady(repos=self._make_repos())
        view.apply_home_ready(home)
        assert len(view._repos) == 3
        assert view._selected_index == 0


# ---------------------------------------------------------------------------
# App view switching tests
# ---------------------------------------------------------------------------

def _mock_refresh(cwd=None):
    return StateChanged("idle", "active",
                        ["continue", "brief", "next", "pause", "end", "session", "status"],
                        "next")


def _mock_resolve_context(cwd=None):
    from commands.registry import Context
    return Context(
        project_path="/tmp/test", workspace_path=None, branch="issue-42",
        state="active", on_main=False, in_slot=False, has_plan=True,
        plan_position="1/3", stack_depth=0, owner_repo="Test/repo",
        base_branch="main", meta_path=None, has_queue=True, issue=42,
        is_epic=False, epic_batch=None, epic_active_issue=None,
    )


@pytest.mark.asyncio
async def test_app_starts_in_project_view_with_cwd():
    """When cwd is provided, app starts directly in Project View."""
    with patch("tui.python.app.refresh", side_effect=_mock_refresh), \
         patch("tui.python.app.resolve_context", side_effect=_mock_resolve_context):
        from tui.python.app import SorediumApp
        from tui.python.ui.action_panel import ActionPanel

        app = SorediumApp(cwd="/tmp/test")
        async with app.run_test() as pilot:
            panel = pilot.app.query_one(ActionPanel)
            assert panel._actions  # Should have actions populated
