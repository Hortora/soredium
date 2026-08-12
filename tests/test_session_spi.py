"""Tests for Session SPI — TmuxProvider and SuspendingProvider."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import subprocess

from commands.events import IssueContext
from tui.python.session import SessionProvider
from tui.python.session.tmux import TmuxProvider
from tui.python.session.suspend import SuspendingProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ctx(issue: int = 42, project: str = "/path/to/soredium") -> IssueContext:
    return IssueContext(
        issue=issue,
        title="Fix scoring bug",
        branch=f"issue-{issue}-fix",
        plan_position="1/3",
        project_path=project,
        workspace_path="/path/to/workspace",
    )


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestProtocolCompliance:
    def test_tmux_has_required_methods(self):
        provider = TmuxProvider()
        assert hasattr(provider, "start")
        assert hasattr(provider, "run")
        assert hasattr(provider, "is_active")
        assert hasattr(provider, "stop")

    def test_suspend_has_required_methods(self):
        provider = SuspendingProvider()
        assert hasattr(provider, "start")
        assert hasattr(provider, "run")
        assert hasattr(provider, "is_active")
        assert hasattr(provider, "stop")


# ---------------------------------------------------------------------------
# TmuxProvider — session name generation
# ---------------------------------------------------------------------------

class TestTmuxSessionName:
    def test_name_from_issue(self):
        provider = TmuxProvider()
        ctx = _ctx(42, "/path/to/soredium")
        assert provider.session_name_for(ctx) == "soredium-soredium-42"

    def test_name_strips_trailing_slash(self):
        provider = TmuxProvider()
        ctx = _ctx(42, "/path/to/soredium/")
        assert provider.session_name_for(ctx) == "soredium-soredium-42"

    def test_name_uses_repo_basename(self):
        provider = TmuxProvider()
        ctx = _ctx(99, "/home/user/projects/engine")
        assert provider.session_name_for(ctx) == "soredium-engine-99"


# ---------------------------------------------------------------------------
# TmuxProvider — lifecycle
# ---------------------------------------------------------------------------

class TestTmuxLifecycle:
    def test_not_active_initially(self):
        provider = TmuxProvider()
        assert provider.is_active() is False

    @patch("subprocess.run")
    def test_start_creates_detached_session(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        provider = TmuxProvider()
        ctx = _ctx()
        provider.start(ctx)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "tmux"
        assert "new-session" in args
        assert "-d" in args
        assert "-s" in args
        name_idx = args.index("-s") + 1
        assert args[name_idx] == "soredium-soredium-42"

    @patch("subprocess.run")
    def test_start_passes_cwd(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        provider = TmuxProvider()
        ctx = _ctx()
        provider.start(ctx)

        args = mock_run.call_args[0][0]
        assert "-c" in args
        c_idx = args.index("-c") + 1
        assert args[c_idx] == "/path/to/soredium"

    @patch("subprocess.run")
    def test_start_uses_configured_cli(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        provider = TmuxProvider(cli_command="/usr/local/bin/claude")
        ctx = _ctx()
        provider.start(ctx)

        args = mock_run.call_args[0][0]
        assert "/usr/local/bin/claude" in args

    @patch("subprocess.run")
    def test_run_attaches_to_session(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        provider = TmuxProvider()
        ctx = _ctx()
        provider.start(ctx)
        mock_run.reset_mock()

        provider.run()

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["tmux", "attach-session", "-t", "soredium-soredium-42"]

    @patch("subprocess.run")
    def test_is_active_checks_tmux(self, mock_run):
        provider = TmuxProvider()
        ctx = _ctx()

        # Simulate start
        mock_run.return_value = MagicMock(returncode=0)
        provider.start(ctx)
        mock_run.reset_mock()

        # Session exists
        mock_run.return_value = MagicMock(returncode=0)
        assert provider.is_active() is True

        # Session gone
        mock_run.return_value = MagicMock(returncode=1)
        assert provider.is_active() is False

    @patch("subprocess.run")
    def test_stop_kills_session(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        provider = TmuxProvider()
        ctx = _ctx()
        provider.start(ctx)
        mock_run.reset_mock()

        provider.stop()

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["tmux", "kill-session", "-t", "soredium-soredium-42"]

    def test_stop_noop_without_start(self):
        provider = TmuxProvider()
        provider.stop()  # Should not raise

    def test_run_noop_without_start(self):
        provider = TmuxProvider()
        provider.run()  # Should not raise


# ---------------------------------------------------------------------------
# SuspendingProvider — lifecycle
# ---------------------------------------------------------------------------

class TestSuspendLifecycle:
    def test_not_active_initially(self):
        provider = SuspendingProvider()
        assert provider.is_active() is False

    def test_start_stores_context(self):
        provider = SuspendingProvider()
        ctx = _ctx()
        provider.start(ctx)
        assert provider._context is ctx

    @patch("subprocess.run")
    def test_run_executes_cli(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        provider = SuspendingProvider()
        ctx = _ctx()
        provider.start(ctx)

        provider.run()

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["claude"]
        assert mock_run.call_args[1].get("cwd") == "/path/to/soredium"

    @patch("subprocess.run")
    def test_run_uses_configured_cli(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        provider = SuspendingProvider(cli_command="/opt/bin/claude")
        ctx = _ctx()
        provider.start(ctx)

        provider.run()

        args = mock_run.call_args[0][0]
        assert args == ["/opt/bin/claude"]

    @patch("subprocess.run")
    def test_not_active_after_run(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        provider = SuspendingProvider()
        ctx = _ctx()
        provider.start(ctx)
        provider.run()
        assert provider.is_active() is False

    def test_stop_clears_context(self):
        provider = SuspendingProvider()
        ctx = _ctx()
        provider.start(ctx)
        provider.stop()
        assert provider._context is None

    def test_run_noop_without_start(self):
        provider = SuspendingProvider()
        provider.run()  # Should not raise


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

class TestAutoDetect:
    @patch("shutil.which", return_value="/usr/bin/tmux")
    def test_tmux_available_returns_tmux_provider(self, _):
        from tui.python.app import SorediumApp
        app = SorediumApp.__new__(SorediumApp)
        provider = app._auto_detect_provider()
        assert isinstance(provider, TmuxProvider)

    @patch("shutil.which", return_value=None)
    def test_tmux_missing_returns_suspend_provider(self, _):
        from tui.python.app import SorediumApp
        app = SorediumApp.__new__(SorediumApp)
        provider = app._auto_detect_provider()
        assert isinstance(provider, SuspendingProvider)
