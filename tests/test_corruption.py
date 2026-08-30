#!/usr/bin/env python3
"""Tests for project/corruption.py — lifecycle corruption detection."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


def _write_plan(path: Path, state: str = "active", branch: str = "issue-42-foo", **extra):
    defaults = {"date": "2026-08-20", "issue-repo": "Hortora/soredium", "covers": "42"}
    defaults.update(extra)
    lines = ["# Work Plan — test", "", "## State",
             f"branch: {branch}", f"state: {state}"]
    for k, v in defaults.items():
        lines.append(f"{k}: {v}")
    lines.extend(["", "## Queue", "- [ ] #42 — Fix foo ← active", ""])
    path.write_text("\n".join(lines))


def _write_plan_no_state(path: Path, branch: str = "issue-42-foo"):
    lines = ["# Work Plan — test", "", "## State",
             f"branch: {branch}", "date: 2026-08-20",
             "", "## Queue", "- [ ] #42 — Fix foo ← active", ""]
    path.write_text("\n".join(lines))


class TestFinding:
    def test_finding_has_required_fields(self):
        from corruption import Finding
        f = Finding(
            scenario="S1_MISSING_STATE",
            severity="warning",
            detail="test detail",
            actions=["accept_default"],
        )
        assert f.scenario == "S1_MISSING_STATE"
        assert f.severity == "warning"
        assert f.detail == "test detail"
        assert f.actions == ["accept_default"]


class TestS1MissingState:
    def test_missing_state_field_returns_warning(self, tmp_path):
        from corruption import check_missing_state
        plan = tmp_path / ".plan"
        _write_plan_no_state(plan)
        finding = check_missing_state(plan)
        assert finding is not None
        assert finding.scenario == "S1_MISSING_STATE"
        assert finding.severity == "warning"
        assert "accept_default" in finding.actions

    def test_present_state_field_returns_none(self, tmp_path):
        from corruption import check_missing_state
        plan = tmp_path / ".plan"
        _write_plan(plan)
        assert check_missing_state(plan) is None

    def test_no_plan_returns_none(self, tmp_path):
        from corruption import check_missing_state
        assert check_missing_state(tmp_path / ".plan") is None


class TestS2InvalidState:
    def test_corrupted_prefix_returns_error(self, tmp_path):
        from corruption import check_invalid_state
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:pro")
        finding = check_invalid_state("corrupted:closing:pro", plan)
        assert finding is not None
        assert finding.scenario == "S2_INVALID_STATE"
        assert finding.severity == "error"
        assert "write_active" in finding.actions
        assert "remove_plan" in finding.actions

    def test_valid_state_returns_none(self, tmp_path):
        from corruption import check_invalid_state
        plan = tmp_path / ".plan"
        _write_plan(plan)
        assert check_invalid_state("active", plan) is None

    def test_empty_state_returns_none(self, tmp_path):
        from corruption import check_invalid_state
        plan = tmp_path / ".plan"
        _write_plan(plan)
        assert check_invalid_state("", plan) is None


class TestS5BranchMismatch:
    def test_mismatch_returns_error(self, tmp_path):
        from corruption import check_branch_mismatch
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="issue-42-foo")
        finding = check_branch_mismatch(plan, tmp_path, current_branch="main", base_branch="main")
        assert finding is not None
        assert finding.scenario == "S5_BRANCH_MISMATCH"
        assert finding.severity == "error"

    def test_matching_branches_returns_none(self, tmp_path):
        from corruption import check_branch_mismatch
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="issue-42-foo")
        assert check_branch_mismatch(plan, tmp_path, current_branch="issue-42-foo", base_branch="main") is None

    def test_main_plan_on_main_returns_none(self, tmp_path):
        from corruption import check_branch_mismatch
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="main")
        assert check_branch_mismatch(plan, tmp_path, current_branch="main", base_branch="main") is None

    def test_no_plan_returns_none(self, tmp_path):
        from corruption import check_branch_mismatch
        assert check_branch_mismatch(tmp_path / ".plan", tmp_path, current_branch="main", base_branch="main") is None

    def test_nonmain_base_branch(self, tmp_path):
        from corruption import check_branch_mismatch
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="develop")
        assert check_branch_mismatch(plan, tmp_path, current_branch="develop", base_branch="develop") is None

    def test_drained_plan_skips_branch_mismatch(self, tmp_path):
        """Drained plans have a stale branch field — don't flag it."""
        from corruption import check_branch_mismatch
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="issue-42-foo", state="drained")
        finding = check_branch_mismatch(plan, tmp_path, current_branch="main", base_branch="main")
        assert finding is None, "Drained plans should not trigger branch mismatch"


class TestS7StalePlanOnMain:
    def test_stale_plan_on_main(self, tmp_path):
        from corruption import check_stale_plan_on_main
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="issue-42-foo", state="active")
        finding = check_stale_plan_on_main(plan, meta_state="active", base_branch="main", on_main=True)
        assert finding is not None
        assert finding.scenario == "S7_STALE_PLAN_ON_MAIN"

    def test_drained_plan_on_main_is_ok(self, tmp_path):
        from corruption import check_stale_plan_on_main
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="main", state="drained")
        assert check_stale_plan_on_main(plan, meta_state="drained", base_branch="main", on_main=True) is None

    def test_main_plan_on_main_is_ok(self, tmp_path):
        from corruption import check_stale_plan_on_main
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="main", state="active")
        assert check_stale_plan_on_main(plan, meta_state="active", base_branch="main", on_main=True) is None

    def test_not_on_main_returns_none(self, tmp_path):
        from corruption import check_stale_plan_on_main
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="issue-42-foo")
        assert check_stale_plan_on_main(plan, meta_state="active", base_branch="main", on_main=False) is None


class TestS6BranchNotExist:
    def test_missing_branch_returns_error(self, tmp_path, monkeypatch):
        from corruption import check_branch_exists
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="issue-42-foo")
        monkeypatch.setattr("corruption.subprocess.run", lambda *a, **kw: type('R', (), {
            'stdout': '', 'returncode': 0,
        })())
        finding = check_branch_exists(plan, tmp_path)
        assert finding is not None
        assert finding.scenario == "S6_BRANCH_NOT_EXIST"
        assert finding.severity == "error"
        assert "remove_plan" in finding.actions

    def test_existing_branch_returns_none(self, tmp_path, monkeypatch):
        from corruption import check_branch_exists
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="issue-42-foo")
        monkeypatch.setattr("corruption.subprocess.run", lambda *a, **kw: type('R', (), {
            'stdout': 'issue-42-foo', 'returncode': 0,
        })())
        assert check_branch_exists(plan, tmp_path) is None

    def test_no_plan_returns_none(self, tmp_path):
        from corruption import check_branch_exists
        assert check_branch_exists(tmp_path / ".plan", tmp_path) is None


class TestS4ClosingPostconditions:
    def test_closing_stamped_without_stamp_commit(self, tmp_path, monkeypatch):
        from corruption import check_closing_postconditions
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:stamped", branch="issue-42-foo")
        monkeypatch.setattr("corruption.subprocess.run", lambda *a, **kw: type('R', (), {
            'stdout': 'abc1234 feat: add feature\n', 'returncode': 0,
        })())
        finding = check_closing_postconditions("closing:stamped", plan, tmp_path, tmp_path, "main")
        assert finding is not None
        assert finding.scenario == "S4_CLOSING_POSTCONDITION"
        assert "continue_close" in finding.actions

    def test_closing_stamped_with_stamp_commit(self, tmp_path, monkeypatch):
        from corruption import check_closing_postconditions
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:stamped", branch="issue-42-foo")
        monkeypatch.setattr("corruption.subprocess.run", lambda *a, **kw: type('R', (), {
            'stdout': 'chore: branch closed — landed as abc on main\n', 'returncode': 0,
        })())
        assert check_closing_postconditions("closing:stamped", plan, tmp_path, tmp_path, "main") is None

    def test_non_closing_state_returns_none(self, tmp_path):
        from corruption import check_closing_postconditions
        plan = tmp_path / ".plan"
        _write_plan(plan)
        assert check_closing_postconditions("active", plan, tmp_path, tmp_path, "main") is None

    def test_closing_review_no_postcondition_check(self, tmp_path):
        from corruption import check_closing_postconditions
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:review")
        assert check_closing_postconditions("closing:review", plan, tmp_path, tmp_path, "main") is None


class TestS3ActiveAllClosed:
    def test_skipped_without_owner_repo(self, tmp_path):
        from corruption import check_active_all_closed
        plan = tmp_path / ".plan"
        _write_plan(plan)
        assert check_active_all_closed(plan, "active", owner_repo="") is None

    def test_skipped_for_non_active_state(self, tmp_path):
        from corruption import check_active_all_closed
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:review")
        assert check_active_all_closed(plan, "closing:review", owner_repo="Org/repo") is None

    def test_all_closed_returns_warning(self, tmp_path, monkeypatch):
        from corruption import check_active_all_closed
        plan = tmp_path / ".plan"
        _write_plan(plan)

        def mock_run(*args, **kwargs):
            return type('R', (), {'stdout': 'CLOSED\n', 'returncode': 0})()

        monkeypatch.setattr("corruption.subprocess.run", mock_run)
        finding = check_active_all_closed(plan, "active", owner_repo="Hortora/soredium")
        assert finding is not None
        assert finding.scenario == "S3_ACTIVE_ALL_CLOSED"
        assert finding.severity == "warning"

    def test_open_issue_returns_none(self, tmp_path, monkeypatch):
        from corruption import check_active_all_closed
        plan = tmp_path / ".plan"
        _write_plan(plan)

        def mock_run(*args, **kwargs):
            return type('R', (), {'stdout': 'OPEN\n', 'returncode': 0})()

        monkeypatch.setattr("corruption.subprocess.run", mock_run)
        assert check_active_all_closed(plan, "active", owner_repo="Hortora/soredium") is None


class TestS8QueueConsistency:
    def test_skipped_without_owner_repo(self, tmp_path):
        from corruption import check_queue_consistency
        plan = tmp_path / ".plan"
        _write_plan(plan)
        assert check_queue_consistency(plan, owner_repo="") is None

    def test_consistent_queue_returns_none(self, tmp_path, monkeypatch):
        from corruption import check_queue_consistency
        plan = tmp_path / ".plan"
        _write_plan(plan)

        def mock_run(*args, **kwargs):
            return type('R', (), {'stdout': 'OPEN\tFix foo\n', 'returncode': 0})()

        monkeypatch.setattr("corruption.subprocess.run", mock_run)
        assert check_queue_consistency(plan, owner_repo="Hortora/soredium") is None

    def test_inconsistent_queue_returns_warning(self, tmp_path, monkeypatch):
        from corruption import check_queue_consistency
        plan = tmp_path / ".plan"
        _write_plan(plan)

        def mock_run(*args, **kwargs):
            return type('R', (), {'stdout': 'CLOSED\tFix foo\n', 'returncode': 0})()

        monkeypatch.setattr("corruption.subprocess.run", mock_run)
        finding = check_queue_consistency(plan, owner_repo="Hortora/soredium")
        assert finding is not None
        assert finding.scenario == "S8_QUEUE_INCONSISTENT"
        assert "sync_plan_with_github" in finding.actions

    def test_cross_repo_title_mismatch_skips(self, tmp_path, monkeypatch):
        from corruption import check_queue_consistency
        plan = tmp_path / ".plan"
        lines = [
            "# Work Plan — test", "", "## State",
            "branch: issue-42-foo", "state: active",
            "date: 2026-08-20", "issue-repo: epic-org/epic-repo",
            "covers: 42", "",
            "## Queue",
            "- [ ] #42 — Fix foo ← active",
            "- [ ] #332 — Local executor base module",
            "",
        ]
        plan.write_text("\n".join(lines))

        def mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            num = cmd[3]
            if num == "42":
                return type('R', (), {'stdout': 'OPEN\tFix foo\n', 'returncode': 0})()
            if num == "332":
                return type('R', (), {'stdout': 'CLOSED\tDocs update\n', 'returncode': 0})()
            return type('R', (), {'stdout': '', 'returncode': 1})()

        monkeypatch.setattr("corruption.subprocess.run", mock_run)
        result = check_queue_consistency(plan, owner_repo="owner-org/project")
        assert result is None

    def test_covers_issue_checked_but_open_not_flagged(self, tmp_path, monkeypatch):
        from corruption import check_queue_consistency
        plan = tmp_path / ".plan"
        lines = [
            "# Work Plan — test", "", "## State",
            "branch: issue-408-epic", "state: active",
            "date: 2026-08-20", "issue-repo: Hortora/soredium",
            "covers: 408", "",
            "## Queue",
            "- [x] #408 — Epic: big feature",
            "- [ ] #409 — Subtask one",
            "",
        ]
        plan.write_text("\n".join(lines))

        def mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            num = cmd[3]
            if num == "408":
                return type('R', (), {'stdout': 'OPEN\tEpic: big feature\n', 'returncode': 0})()
            if num == "409":
                return type('R', (), {'stdout': 'OPEN\tSubtask one\n', 'returncode': 0})()
            return type('R', (), {'stdout': '', 'returncode': 1})()

        monkeypatch.setattr("corruption.subprocess.run", mock_run)
        result = check_queue_consistency(plan, owner_repo="Hortora/soredium")
        assert result is None

    def test_non_covers_checked_but_open_still_flagged(self, tmp_path, monkeypatch):
        from corruption import check_queue_consistency
        plan = tmp_path / ".plan"
        lines = [
            "# Work Plan — test", "", "## State",
            "branch: issue-408-epic", "state: active",
            "date: 2026-08-20", "issue-repo: Hortora/soredium",
            "covers: 408", "",
            "## Queue",
            "- [x] #408 — Epic: big feature",
            "- [x] #409 — Subtask one",
            "",
        ]
        plan.write_text("\n".join(lines))

        def mock_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            num = cmd[3]
            if num == "408":
                return type('R', (), {'stdout': 'OPEN\tEpic: big feature\n', 'returncode': 0})()
            if num == "409":
                return type('R', (), {'stdout': 'OPEN\tSubtask one\n', 'returncode': 0})()
            return type('R', (), {'stdout': '', 'returncode': 1})()

        monkeypatch.setattr("corruption.subprocess.run", mock_run)
        result = check_queue_consistency(plan, owner_repo="Hortora/soredium")
        assert result is not None
        assert "#409 checked but OPEN" in result.detail
        assert "#408" not in result.detail


class TestS9OrphanedWksp:
    def test_wksp_to_non_git_dir_returns_warning(self, tmp_path):
        from corruption import check_orphaned_wksp
        project = tmp_path / "project"
        project.mkdir()
        target = tmp_path / "not-a-repo"
        target.mkdir()
        (project / "wksp").symlink_to(target)
        finding = check_orphaned_wksp(project)
        assert finding is not None
        assert finding.scenario == "S9_ORPHANED_WKSP"
        assert finding.severity == "error"
        assert "repoint_wksp" in finding.actions

    def test_wksp_to_git_repo_returns_none(self, tmp_path):
        from corruption import check_orphaned_wksp
        project = tmp_path / "project"
        project.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".git").mkdir()
        (project / "wksp").symlink_to(workspace)
        assert check_orphaned_wksp(project) is None

    def test_wksp_to_subdir_of_git_repo_returns_none(self, tmp_path):
        from corruption import check_orphaned_wksp
        project = tmp_path / "project"
        project.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".git").mkdir()
        subdir = workspace / "engine"
        subdir.mkdir()
        (project / "wksp").symlink_to(subdir)
        assert check_orphaned_wksp(project) is None

    def test_no_wksp_symlink_returns_none(self, tmp_path):
        from corruption import check_orphaned_wksp
        project = tmp_path / "project"
        project.mkdir()
        assert check_orphaned_wksp(project) is None

    def test_dangling_wksp_symlink_returns_warning(self, tmp_path):
        from corruption import check_orphaned_wksp
        project = tmp_path / "project"
        project.mkdir()
        (project / "wksp").symlink_to("/nonexistent/path")
        finding = check_orphaned_wksp(project)
        assert finding is not None
        assert finding.scenario == "S9_ORPHANED_WKSP"


class TestDiagnose:
    def test_healthy_state_returns_empty(self, tmp_path, monkeypatch):
        from corruption import diagnose
        plan = tmp_path / ".plan"
        _write_plan(plan, branch="issue-42-foo")
        monkeypatch.setattr("corruption.subprocess.run", lambda *a, **kw: type('R', (), {
            'stdout': 'issue-42-foo', 'returncode': 0,
        })())
        findings = diagnose(
            plan_path=plan, meta_state="active",
            project=tmp_path, workspace=tmp_path,
            base_branch="main", current_branch="issue-42-foo", on_main=False,
        )
        assert findings == []

    def test_no_plan_returns_empty(self, tmp_path):
        from corruption import diagnose
        findings = diagnose(
            plan_path=None, meta_state="",
            project=tmp_path, workspace=tmp_path,
        )
        assert findings == []

    def test_orphaned_wksp_detected_without_plan(self, tmp_path):
        from corruption import diagnose
        project = tmp_path / "project"
        project.mkdir()
        target = tmp_path / "not-a-repo"
        target.mkdir()
        (project / "wksp").symlink_to(target)
        findings = diagnose(
            plan_path=None, meta_state="",
            project=project, workspace=project,
        )
        assert len(findings) == 1
        assert findings[0].scenario == "S9_ORPHANED_WKSP"

    def test_invalid_state_short_circuits(self, tmp_path, monkeypatch):
        from corruption import diagnose
        plan = tmp_path / ".plan"
        _write_plan(plan, state="bogus", branch="issue-42-foo")
        monkeypatch.setattr("corruption.subprocess.run", lambda *a, **kw: type('R', (), {
            'stdout': 'issue-42-foo', 'returncode': 0,
        })())
        findings = diagnose(
            plan_path=plan, meta_state="corrupted:bogus",
            project=tmp_path, workspace=tmp_path,
            current_branch="issue-42-foo",
        )
        scenarios = {f.scenario for f in findings}
        assert "S2_INVALID_STATE" in scenarios
        assert "S3_ACTIVE_ALL_CLOSED" not in scenarios
        assert "S4_CLOSING_POSTCONDITION" not in scenarios
        assert "S6_BRANCH_NOT_EXIST" not in scenarios

    def test_multiple_findings_returned(self, tmp_path, monkeypatch):
        from corruption import diagnose
        plan = tmp_path / ".plan"
        _write_plan_no_state(plan, branch="issue-42-foo")
        monkeypatch.setattr("corruption.subprocess.run", lambda *a, **kw: type('R', (), {
            'stdout': '', 'returncode': 0,
        })())
        findings = diagnose(
            plan_path=plan, meta_state="active",
            project=tmp_path, workspace=tmp_path,
            current_branch="main", on_main=True, base_branch="main",
        )
        scenarios = {f.scenario for f in findings}
        assert "S1_MISSING_STATE" in scenarios
        assert "S7_STALE_PLAN_ON_MAIN" in scenarios
