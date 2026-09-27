"""Tests for auto-recovery in corruption detection."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from corruption import (
    Finding,
    check_stale_plan_on_main,
    check_active_all_closed,
    check_branch_exists,
    check_invalid_state,
    diagnose,
)


class TestFindingAutoRecoveryFields:
    def test_finding_has_auto_recoverable_field(self):
        f = Finding(scenario="test", severity="warning", detail="test")
        assert hasattr(f, "auto_recoverable")
        assert f.auto_recoverable is False

    def test_finding_has_auto_action_field(self):
        f = Finding(scenario="test", severity="warning", detail="test")
        assert hasattr(f, "auto_action")
        assert f.auto_action == ""

    def test_auto_recoverable_finding(self):
        f = Finding(
            scenario="test", severity="warning", detail="test",
            auto_recoverable=True, auto_action="remove_plan",
        )
        assert f.auto_recoverable is True
        assert f.auto_action == "remove_plan"


class TestStalePlanOnMainAutoRecovery:
    def test_stale_plan_on_main_is_auto_recoverable(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nbranch: old-branch\nstate: active\n\n## Queue\n")
        f = check_stale_plan_on_main(plan, "active", "main", on_main=True)
        assert f is not None
        assert f.auto_recoverable is True
        assert f.auto_action == "remove_plan"


class TestBranchNotExistAutoRecovery:
    def test_orphaned_plan_no_branch_anywhere(self, tmp_path, monkeypatch):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nbranch: ghost-branch\nstate: active\n\n## Queue\n")

        def mock_run(*args, **kwargs):
            result = type("R", (), {"stdout": "", "returncode": 1})()
            return result
        monkeypatch.setattr(subprocess, "run", mock_run)

        f = check_branch_exists(plan, tmp_path)
        assert f is not None
        assert f.auto_recoverable is True
        assert f.auto_action == "remove_plan"

    def test_branch_on_remote_not_auto_recoverable(self, tmp_path, monkeypatch):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nbranch: remote-branch\nstate: active\n\n## Queue\n")

        call_count = [0]
        def mock_run(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return type("R", (), {"stdout": "", "returncode": 0})()
            return type("R", (), {"stdout": "abc123 refs/heads/remote-branch", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", mock_run)

        f = check_branch_exists(plan, tmp_path)
        assert f is not None
        assert f.auto_recoverable is False


class TestInvalidStateAutoRecovery:
    def test_invalid_state_not_auto_recoverable(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: corrupted:banana\n\n## Queue\n")
        f = check_invalid_state("corrupted:banana", plan)
        assert f is not None
        assert f.auto_recoverable is False


class TestDiagnoseAutoRecoveredOutput:
    def test_all_auto_recoverable_returns_flag(self, tmp_path, monkeypatch):
        """When all findings are auto-recoverable, diagnose output includes the flag."""
        plan = tmp_path / ".plan"
        plan.write_text("## State\nbranch: old-branch\nstate: active\n\n## Queue\n")

        def mock_git(repo, *args, timeout=10):
            return ("", 1)
        monkeypatch.setattr("corruption._git", mock_git)

        def mock_run(*args, **kwargs):
            return type("R", (), {"stdout": "", "returncode": 1})()
        monkeypatch.setattr(subprocess, "run", mock_run)

        findings = diagnose(
            plan_path=plan,
            meta_state="active",
            project=tmp_path,
            workspace=tmp_path,
            base_branch="main",
            current_branch="main",
            on_main=True,
        )
        auto_findings = [f for f in findings if f.auto_recoverable]
        assert len(auto_findings) > 0

    def test_mixed_findings_not_all_auto(self, tmp_path):
        """When some findings are not auto-recoverable, not all are flagged."""
        f1 = Finding("S1", "warning", "test", auto_recoverable=True, auto_action="remove_plan")
        f2 = Finding("S2", "error", "test", auto_recoverable=False)
        assert not all(f.auto_recoverable for f in [f1, f2])

    def test_auto_action_preserved_in_finding(self):
        f = Finding(
            "S7_STALE_PLAN_ON_MAIN", "warning", "stale plan",
            actions=["switch_to_branch", "remove_plan"],
            auto_recoverable=True, auto_action="remove_plan",
        )
        assert f.auto_action == "remove_plan"
        assert f.auto_action in f.actions
