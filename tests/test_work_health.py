#!/usr/bin/env python3
"""Tests for project/work_health.py — unified work state validation."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
from work_health import (
    check_branch_closure,
    check_dirty_main,
    check_main_divergence,
    check_meta_consistency,
    check_partial_pause,
    check_partial_resume,
    check_pause_stack,
    check_plan_state,
    check_workspace_alignment,
    format_resume_display,
    run_checks,
)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True,
                    capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                    cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                    cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, check=True,
                    capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True,
                    capture_output=True)
    return path


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo)] + list(args),
                    check=True, capture_output=True)


class TestMetaConsistency:

    def test_no_meta_is_ok(self, tmp_path):
        workspace = _init_repo(tmp_path / "wksp")
        result = check_meta_consistency(str(tmp_path / "proj"), str(workspace))
        assert "STATUS=ok" in result

    def test_orphaned_meta_on_main(self, tmp_path):
        workspace = _init_repo(tmp_path / "wksp")
        design = workspace / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: issue-42-foo\nstate: active\n")
        result = check_meta_consistency(str(tmp_path / "proj"), str(workspace))
        assert "STATUS=warn" in result
        assert "orphaned" in result

    def test_matching_branch(self, tmp_path):
        workspace = _init_repo(tmp_path / "wksp")
        subprocess.run(["git", "checkout", "-b", "issue-42-foo"], cwd=workspace,
                        check=True, capture_output=True)
        design = workspace / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: issue-42-foo\nstate: active\n")
        result = check_meta_consistency(str(tmp_path / "proj"), str(workspace))
        assert "STATUS=ok" in result


class TestPauseStack:

    def test_no_stack_is_ok(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        result = check_pause_stack(str(project), str(workspace))
        assert "STATUS=ok" in result

    def test_stale_stack_entry(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        design = workspace / "design"
        design.mkdir()
        (design / ".pause-stack").write_text(
            "- branch: deleted-branch\n  issue: 999\n  paused: 2026-08-01\n"
        )
        result = check_pause_stack(str(project), str(workspace))
        assert "STATUS=warn" in result
        assert "deleted-branch" in result

    def test_valid_stack_entry(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        subprocess.run(["git", "checkout", "-b", "issue-42-foo"], cwd=project,
                        check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=project,
                        check=True, capture_output=True)
        design = workspace / "design"
        design.mkdir()
        (design / ".pause-stack").write_text(
            "- branch: issue-42-foo\n  issue: 42\n  paused: 2026-08-01\n"
        )
        result = check_pause_stack(str(project), str(workspace))
        assert "STATUS=ok" in result


class TestWorkspaceAlignment:

    def test_same_repo_is_ok(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        result = check_workspace_alignment(str(repo), str(repo))
        assert "STATUS=ok" in result

    def test_misaligned_branches(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=workspace,
                        check=True, capture_output=True)
        result = check_workspace_alignment(str(project), str(workspace))
        assert "STATUS=warn" in result
        assert "workspace on 'feature'" in result

    def test_aligned_branches(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        result = check_workspace_alignment(str(project), str(workspace))
        assert "STATUS=ok" in result


class TestDirtyMain:

    def test_clean_main(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        result = check_dirty_main(str(project), str(tmp_path / "wksp"))
        assert "STATUS=ok" in result

    def test_dirty_main(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        (project / "dirty.txt").write_text("uncommitted")
        result = check_dirty_main(str(project), str(tmp_path / "wksp"))
        assert "STATUS=warn" in result
        assert "uncommitted" in result

    def test_not_on_main_is_ok(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=project,
                        check=True, capture_output=True)
        (project / "dirty.txt").write_text("uncommitted")
        result = check_dirty_main(str(project), str(tmp_path / "wksp"))
        assert "STATUS=ok" in result


class TestPartialPause:

    def test_no_intent_file(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        result = check_partial_pause(str(project), str(workspace))
        assert "STATUS=ok" in result

    def test_pausing_detected(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        _git(project, "checkout", "-b", "issue-123-foo")
        design = workspace / "design"
        design.mkdir()
        (design / ".pausing").write_text(
            "branch: issue-123-foo\nstarted: 2026-08-06T14:30:00Z\n"
            "wip_project: done\nwip_workspace: done\n"
            "stack_push: pending\ncheckout_main: pending\n"
        )
        result = check_partial_pause(str(project), str(workspace))
        assert "STATUS=warn" in result
        assert "issue-123-foo" in result
        assert "stack_push=pending" in result

    def test_stale_pausing_removed_when_pause_completed(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        design = workspace / "design"
        design.mkdir()
        (design / ".pausing").write_text(
            "branch: issue-123-foo\nstarted: 2026-08-06T14:30:00Z\n"
            "wip_project: done\nwip_workspace: done\n"
            "stack_push: done\ncheckout_main: done\n"
        )
        (design / ".pause-stack").write_text("- branch: issue-123-foo\n  issue: 123\n")
        result = check_partial_pause(str(project), str(workspace))
        assert "STATUS=ok" in result
        assert not (design / ".pausing").exists()


class TestPartialResume:

    def test_no_intent_file(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        result = check_partial_resume(str(project), str(workspace))
        assert "STATUS=ok" in result

    def test_resuming_detected(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        design = workspace / "design"
        design.mkdir()
        (design / ".pause-stack").write_text("- branch: issue-123-foo\n  issue: 123\n")
        (design / ".resuming").write_text(
            "branch: issue-123-foo\nstarted: 2026-08-06T14:30:00Z\n"
            "stack_pop: done\ncheckout: pending\n"
            "rebase: pending\nwip_reset: pending\n"
        )
        result = check_partial_resume(str(project), str(workspace))
        assert "STATUS=warn" in result
        assert "issue-123-foo" in result
        assert "checkout=pending" in result

    def test_stale_resuming_removed_when_resume_completed(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        _git(project, "checkout", "-b", "issue-123-foo")
        design = workspace / "design"
        design.mkdir()
        (design / ".resuming").write_text(
            "branch: issue-123-foo\nstarted: 2026-08-06T14:30:00Z\n"
            "stack_pop: done\ncheckout: done\n"
            "rebase: done\nwip_reset: done\n"
        )
        result = check_partial_resume(str(project), str(workspace))
        assert "STATUS=ok" in result
        assert not (design / ".resuming").exists()


class TestBranchClosure:

    def test_no_branches_to_check(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        result = check_branch_closure(str(project), str(workspace))
        assert "STATUS=ok" in result

    def test_merged_unstamped_detected(self, tmp_path):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        subprocess.run(["git", "checkout", "-b", "issue-42-foo"], cwd=project,
                        check=True, capture_output=True)
        (project / "work.txt").write_text("work")
        subprocess.run(["git", "add", "."], cwd=project, check=True,
                        capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: work"], cwd=project,
                        check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=project, check=True,
                        capture_output=True)
        subprocess.run(["git", "rebase", "issue-42-foo"], cwd=project,
                        check=True, capture_output=True)
        design = workspace / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: issue-42-foo\nstate: active\n")
        subprocess.run(["git", "checkout", "-b", "issue-42-foo"], cwd=workspace,
                        check=True, capture_output=True)
        result = check_branch_closure(str(project), str(workspace))
        assert "STATUS=warn" in result
        assert "MERGED_UNSTAMPED" in result


class TestPlanState:

    def _write_plan(self, workspace, content):
        design = Path(workspace) / "design"
        design.mkdir(exist_ok=True)
        (design / ".plan").write_text(content)

    def test_no_plan_is_ok(self, tmp_path):
        workspace = _init_repo(tmp_path / "wksp")
        result = check_plan_state(str(tmp_path / "proj"), str(workspace))
        assert "STATUS=ok" in result

    def test_no_owner_repo_skips(self, tmp_path):
        workspace = _init_repo(tmp_path / "wksp")
        self._write_plan(workspace, (
            "# Work Plan — test\n\n"
            "## Queue\n"
            "- [ ] #100 — some issue ← active\n\n"
            "## Session State\nCurrent: #100\n"
        ))
        result = check_plan_state(str(tmp_path / "proj"), str(workspace), owner_repo="")
        assert "STATUS=skip" in result

    def test_all_completed_is_ok(self, tmp_path):
        workspace = _init_repo(tmp_path / "wksp")
        self._write_plan(workspace, (
            "# Work Plan — test\n\n"
            "## Queue\n"
            "- [x] #100 — done issue\n\n"
            "## Session State\nCurrent: #100\n"
        ))
        result = check_plan_state(str(tmp_path / "proj"), str(workspace), owner_repo="Hortora/soredium")
        assert "STATUS=ok" in result


class TestMarkCompleted:

    def test_mark_completed_public_api(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
        from plan_manager import mark_completed, parse_plan
        plan_path = tmp_path / ".plan"
        plan_path.write_text(
            "# Work Plan — test\n\n"
            "## Queue\n"
            "- [ ] #100 — first issue ← active\n"
            "- [ ] #101 — second issue\n\n"
            "## Session State\nCurrent: #100\n"
        )
        changed = mark_completed(plan_path, 100)
        assert changed is True
        tree = parse_plan(plan_path)
        assert tree.queue[0].completed is True

    def test_mark_completed_nonexistent_issue(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
        from plan_manager import mark_completed
        plan_path = tmp_path / ".plan"
        plan_path.write_text(
            "# Work Plan — test\n\n"
            "## Queue\n"
            "- [ ] #100 — first issue ← active\n\n"
            "## Session State\nCurrent: #100\n"
        )
        changed = mark_completed(plan_path, 999)
        assert changed is False


class TestResumeDisplay:

    def _write_plan(self, workspace, content):
        design = Path(workspace) / "design"
        design.mkdir(exist_ok=True)
        (design / ".plan").write_text(content)

    def test_with_plan(self, tmp_path):
        workspace = tmp_path / "wksp"
        workspace.mkdir()
        self._write_plan(workspace, (
            "# Work Plan — test\n\n"
            "## Queue\n"
            "- [x] #142 — completed issue\n"
            "- [ ] #123 — active issue ← active\n"
            "- [ ] #155 — pending issue\n\n"
            "## Session State\nCurrent: #123\nStarted: 2026-08-06\n"
        ))
        output = format_resume_display(str(workspace))
        assert "#142" in output
        assert "#123" in output
        assert "(current)" in output
        assert "3 items, 1 complete, 1 active" in output

    def test_no_plan(self, tmp_path):
        workspace = tmp_path / "wksp"
        workspace.mkdir()
        output = format_resume_display(str(workspace))
        assert output == ""

    def test_with_health_annotations(self, tmp_path):
        workspace = tmp_path / "wksp"
        workspace.mkdir()
        self._write_plan(workspace, (
            "# Work Plan — test\n\n"
            "## Queue\n"
            "- [ ] #100 — some issue ← active\n\n"
            "## Session State\nCurrent: #100\n"
        ))
        health_output = "CHECK=plan_state STATUS=changed DETAIL=#55 now CLOSED"
        output = format_resume_display(str(workspace), health_output)
        assert "work_health: #55 now CLOSED" in output


class TestRunChecksIntegration:

    def test_clean_entry_scope(self, tmp_path, capsys):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        run_checks("entry", str(project), str(workspace))
        captured = capsys.readouterr()
        assert "FIXED=0" in captured.out
        assert "WARNINGS=0" in captured.out
        assert "ERRORS=0" in captured.out
        assert captured.out.count("CHECK=") == 9

    def test_entry_scope_includes_plan_state_when_owner_repo_provided(self, tmp_path, capsys):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        run_checks("entry", str(project), str(workspace), owner_repo="Hortora/soredium")
        captured = capsys.readouterr()
        assert "CHECK=plan_state" in captured.out

    def test_entry_scope_excludes_plan_state_without_owner_repo(self, tmp_path, capsys):
        project = _init_repo(tmp_path / "proj")
        workspace = _init_repo(tmp_path / "wksp")
        run_checks("entry", str(project), str(workspace))
        captured = capsys.readouterr()
        assert "CHECK=plan_state" not in captured.out
