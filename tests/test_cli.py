"""Tests for CLI entry point — soredium command."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


CLI_MODULE = str(Path(__file__).parent.parent / "cli")


class TestCliHelp:
    def test_no_args_exits_with_error(self):
        result = subprocess.run(
            [sys.executable, "-m", "cli"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
        parsed = json.loads(result.stdout.strip())
        assert "usage" in parsed["data"]["error"].lower()


class TestCliRouting:
    def test_unknown_command(self):
        result = subprocess.run(
            [sys.executable, "-m", "cli", "nonexistent"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
        parsed = json.loads(result.stdout.strip())
        assert "unknown" in parsed["data"]["error"].lower()


class TestCliSerialise:
    def test_serialise_event(self):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from cli.__main__ import _serialise_event
        from commands.events import StatusReady

        line = _serialise_event(StatusReady(
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

        parsed = json.loads(line)
        assert parsed["type"] == "StatusReady"
        assert parsed["data"]["branch"] == "issue-42"
        assert parsed["data"]["state"] == "active"

    def test_serialise_includes_type_field(self):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from cli.__main__ import _serialise_event
        from commands.events import BriefReady, HealthCheck

        line = _serialise_event(BriefReady(
            issue=42, branch="issue-42", state="active",
            queue_position="1/3",
            health=[HealthCheck("test", "ok", None)],
            is_epic=False, epic_batch=None, epic_active_issue=None,
        ))

        parsed = json.loads(line)
        assert parsed["type"] == "BriefReady"
