"""Tests for CLI entry point — soredium command."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


CLI_MODULE = str(Path(__file__).parent.parent / "cli")


class TestCliHelp:
    def test_help_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "cli", "--help"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "soredium" in result.stdout.lower()

    def test_no_args_shows_usage(self):
        result = subprocess.run(
            [sys.executable, "-m", "cli"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 2


class TestCliRouting:
    def test_unknown_command(self):
        result = subprocess.run(
            [sys.executable, "-m", "cli", "nonexistent"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 2
        assert "unknown" in result.stderr.lower()


class TestCliEmit:
    def test_emit_serialises_event(self):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from cli.__main__ import emit
        from commands.events import StatusReady

        import io
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            emit(StatusReady(
                branch="issue-42",
                state="active",
                on_main=False,
                in_slot=False,
                has_plan=True,
                plan_position="1/3",
                stack_depth=0,
                owner_repo="Hortora/soredium",
                base_branch="main",
            ))

        line = buf.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["type"] == "StatusReady"
        assert parsed["branch"] == "issue-42"
        assert parsed["state"] == "active"

    def test_emit_includes_type_field(self):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from cli.__main__ import emit
        from commands.events import BriefReady, HealthCheck

        import io
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            emit(BriefReady(
                issue=42, branch="issue-42", state="active",
                queue_position="1/3",
                health=[HealthCheck("test", "ok", None)],
                is_epic=False, epic_batch=None, epic_active_issue=None,
            ))

        parsed = json.loads(buf.getvalue().strip())
        assert parsed["type"] == "BriefReady"


class TestCliArgParsing:
    def test_parse_start_issues(self):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from cli.__main__ import _parse_args

        result = _parse_args("start", ["#42", "#43", "100"])
        assert result["issues"] == [42, 43, 100]

    def test_parse_start_no_issues(self):
        from cli.__main__ import _parse_args

        result = _parse_args("start", [])
        assert result["issues"] == []

    def test_parse_quickfix_message(self):
        from cli.__main__ import _parse_args

        result = _parse_args("quick-fix", ["fix:", "broken", "test"])
        assert result["message"] == "fix: broken test"

    def test_parse_quickfix_strips_yes(self):
        from cli.__main__ import _parse_args

        result = _parse_args("quick-fix", ["--yes", "fix:", "it"])
        assert result["message"] == "fix: it"

    def test_parse_resume_branch(self):
        from cli.__main__ import _parse_args

        result = _parse_args("resume", ["issue-42-fix"])
        assert result["branch"] == "issue-42-fix"

    def test_parse_resume_no_branch(self):
        from cli.__main__ import _parse_args

        result = _parse_args("resume", [])
        assert "branch" not in result

    def test_parse_status_empty(self):
        from cli.__main__ import _parse_args

        result = _parse_args("status", [])
        assert result == {}


class TestCliCommands:
    def test_known_commands_complete(self):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from cli.__main__ import COMMANDS

        expected = {
            "brief", "continue", "start", "next", "end", "pause",
            "resume", "quick-fix", "what-next", "status", "abort",
        }
        assert COMMANDS == expected
