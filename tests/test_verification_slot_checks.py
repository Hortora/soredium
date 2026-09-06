"""Tests for verification/slot_checks.py"""

import subprocess
from pathlib import Path

from verification.slot_checks import (
    check_absolute_symlinks,
    check_claude_md_paths,
    check_duplicate_plan_items,
    check_plan_branch_matches_slot,
    check_workspace_clone_is_git_repo,
    check_workspace_content_in_project,
    verify_stamp_sha,
)


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(path)] + list(args),
        capture_output=True, text=True, check=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("init\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")
    return path


class TestCheckAbsoluteSymlinks:
    def test_no_symlinks(self, tmp_path):
        clone = tmp_path / "slot" / "engine"
        clone.mkdir(parents=True)
        (clone / "src").mkdir()
        assert check_absolute_symlinks(clone, tmp_path / "slot") == []

    def test_relative_symlink_ok(self, tmp_path):
        slot = tmp_path / "slot"
        clone = slot / "engine"
        clone.mkdir(parents=True)
        target = slot / "wsp-engine"
        target.mkdir()
        (clone / "wksp").symlink_to("../wsp-engine")
        assert check_absolute_symlinks(clone, slot) == []

    def test_absolute_symlink_inside_slot_ok(self, tmp_path):
        slot = tmp_path / "slot"
        clone = slot / "engine"
        clone.mkdir(parents=True)
        target = slot / "wsp-engine"
        target.mkdir()
        (clone / "wksp").symlink_to(str(target))
        assert check_absolute_symlinks(clone, slot) == []

    def test_absolute_symlink_outside_slot_error(self, tmp_path):
        slot = tmp_path / "slot"
        clone = slot / "engine"
        clone.mkdir(parents=True)
        outside = tmp_path / "other"
        outside.mkdir()
        (clone / "wksp").symlink_to("/Users/someone/other/workspace")
        findings = check_absolute_symlinks(clone, slot)
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert findings[0].category == "slot-absolute-symlink"


class TestCheckClaudeMdPaths:
    def test_no_file(self, tmp_path):
        assert check_claude_md_paths(tmp_path / "CLAUDE.md", tmp_path) == []

    def test_clean_content(self, tmp_path):
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("# Project\n\nNo absolute paths here.\n")
        assert check_claude_md_paths(claude, tmp_path) == []

    def test_absolute_path_inside_boundary(self, tmp_path):
        claude = tmp_path / "CLAUDE.md"
        claude.write_text(f"add-dir {tmp_path}/src\n")
        assert check_claude_md_paths(claude, tmp_path) == []

    def test_absolute_path_outside_boundary(self, tmp_path):
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("add-dir /Users/someone/other/project\n")
        findings = check_claude_md_paths(claude, tmp_path)
        assert len(findings) == 1
        assert findings[0].category == "claude-md-absolute-paths"

    def test_symlink_with_absolute_target(self, tmp_path):
        target = tmp_path / "real-claude.md"
        target.write_text("clean content\n")
        link = tmp_path / "CLAUDE.md"
        link.symlink_to("/Users/someone/project/CLAUDE.md")
        findings = check_claude_md_paths(link, tmp_path)
        assert any(f.category == "claude-md-absolute-symlink" for f in findings)


class TestCheckWorkspaceContentInProject:
    def test_no_file(self, tmp_path):
        assert check_workspace_content_in_project(tmp_path / "CLAUDE.md") == []

    def test_project_content_ok(self, tmp_path):
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("# CLAUDE.md\n\nProject instructions.\n")
        assert check_workspace_content_in_project(claude) == []

    def test_workspace_header_detected(self, tmp_path):
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("# Workspace — casehub/engine\n\nWorkspace content.\n")
        findings = check_workspace_content_in_project(claude)
        assert len(findings) == 1
        assert findings[0].category == "project-has-workspace-content"

    def test_empty_file(self, tmp_path):
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("")
        assert check_workspace_content_in_project(claude) == []


class TestVerifyStampSha:
    def test_no_stamp(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        _git(repo, "commit", "--allow-empty", "-m", "feat: something")
        assert verify_stamp_sha(repo, "feature") == []

    def test_valid_stamp(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        _git(repo, "checkout", "-b", "feature")
        _git(repo, "commit", "--allow-empty", "-m",
             f"chore: branch closed — landed as {sha} on main")
        assert verify_stamp_sha(repo, "feature") == []

    def test_invalid_stamp_sha(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feature")
        _git(repo, "commit", "--allow-empty", "-m",
             "chore: branch closed — landed as deadbeef123456 on main")
        findings = verify_stamp_sha(repo, "feature")
        assert len(findings) == 1
        assert findings[0].category == "invalid-stamp-sha"

    def test_nonexistent_branch(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        assert verify_stamp_sha(repo, "nonexistent") == []


class TestCheckWorkspaceCloneIsGitRepo:
    def test_valid_git_repo(self, tmp_path):
        repo = _init_repo(tmp_path / "wsp-engine")
        assert check_workspace_clone_is_git_repo(repo) == []

    def test_not_a_repo(self, tmp_path):
        d = tmp_path / "wsp-engine"
        d.mkdir()
        findings = check_workspace_clone_is_git_repo(d)
        assert len(findings) == 1
        assert findings[0].category == "broken-wsp-clone"

    def test_nonexistent(self, tmp_path):
        findings = check_workspace_clone_is_git_repo(tmp_path / "missing")
        assert len(findings) == 1
        assert findings[0].category == "broken-wsp-clone"


class TestCheckPlanBranchMatchesSlot:
    def test_matching_branch(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("branch: issue-42-fix\nstate: active\n")
        assert check_plan_branch_matches_slot(plan, "issue-42-fix") == []

    def test_mismatched_branch(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("branch: issue-42-fix\nstate: active\n")
        findings = check_plan_branch_matches_slot(plan, "issue-99-other")
        assert len(findings) == 1
        assert findings[0].category == "stale-plan"

    def test_no_plan_file(self, tmp_path):
        assert check_plan_branch_matches_slot(tmp_path / ".plan", "any") == []

    def test_empty_slot_branch(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("branch: issue-42-fix\nstate: active\n")
        assert check_plan_branch_matches_slot(plan, "") == []


class TestCheckDuplicatePlanItems:
    def test_no_duplicates(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("- [x] #10 done\n- [ ] #11 todo\n- [ ] #12 todo\n")
        assert check_duplicate_plan_items(plan) == []

    def test_circular_duplicates(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("- [x] #10 done\n- [ ] #10 todo again\n- [ ] #11 todo\n")
        findings = check_duplicate_plan_items(plan)
        assert len(findings) == 1
        assert findings[0].category == "plan-circular-dupes"
        assert "#10" in findings[0].message

    def test_no_plan_file(self, tmp_path):
        assert check_duplicate_plan_items(tmp_path / ".plan") == []

    def test_empty_plan(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("")
        assert check_duplicate_plan_items(plan) == []
