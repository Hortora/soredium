"""Tests for verification/postconditions.py"""

import subprocess
from pathlib import Path

from verification.postconditions import (
    post_create_slot,
    pre_work_start,
    pre_work_start_attic_guard,
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


class TestPostCreateSlot:
    def test_clean_slot(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        engine = _init_repo(slot / "engine")
        (engine / "CLAUDE.md").write_text("# CLAUDE.md\n\nClean content.\n")
        wsp = _init_repo(slot / "wsp-engine")
        (wsp / ".workspace").touch()
        (wsp / "CLAUDE.md").write_text("# Workspace\nClean.\n")
        assert post_create_slot(slot) == []

    def test_absolute_symlink_detected(self, tmp_path):
        slot = tmp_path / "slot"
        engine = _init_repo(slot / "engine")
        (engine / "wksp").symlink_to("/Users/someone/workspace")
        findings = post_create_slot(slot)
        assert any(f.category == "slot-absolute-symlink" for f in findings)

    def test_non_git_dirs_skipped(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        plain = slot / "wsp-engine"
        plain.mkdir()
        assert post_create_slot(slot) == []

    def test_claude_md_outside_boundary(self, tmp_path):
        slot = tmp_path / "slot"
        engine = _init_repo(slot / "engine")
        (engine / "CLAUDE.md").write_text("add-dir /Users/someone/other/project\n")
        findings = post_create_slot(slot)
        assert any(f.category == "claude-md-absolute-paths" for f in findings)

    def test_workspace_content_in_project(self, tmp_path):
        slot = tmp_path / "slot"
        engine = _init_repo(slot / "engine")
        (engine / "CLAUDE.md").write_text("# Workspace — casehub/engine\n\nWorkspace.\n")
        findings = post_create_slot(slot)
        assert any(f.category == "project-has-workspace-content" for f in findings)

    def test_workspace_clone_skips_project_content_check(self, tmp_path):
        """Workspace clones with .workspace marker skip the project-content check."""
        slot = tmp_path / "slot"
        wsp = _init_repo(slot / "wsp-engine")
        (wsp / ".workspace").touch()
        (wsp / "CLAUDE.md").write_text("# Workspace — casehub/engine\n\nExpected.\n")
        assert post_create_slot(slot) == []

    def test_dot_dirs_skipped(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / ".m2").mkdir()
        (slot / ".hidden").mkdir()
        assert post_create_slot(slot) == []


class TestPreWorkStart:
    def test_no_plan(self, tmp_path):
        assert pre_work_start(tmp_path, branch="issue-42") == []

    def test_clean_plan(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("branch: issue-42\nstate: active\n")
        assert pre_work_start(tmp_path, branch="issue-42") == []

    def test_stuck_close_detected(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("branch: issue-42\nstate: closing:review\n")
        findings = pre_work_start(tmp_path, branch="issue-42")
        assert any(f.category == "stuck-close" for f in findings)

    def test_branch_mismatch_detected(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("branch: issue-99-other\nstate: active\n")
        findings = pre_work_start(tmp_path, branch="issue-42")
        assert any(f.category == "stale-plan" for f in findings)

    def test_no_branch_arg_skips_match(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("branch: issue-99\nstate: active\n")
        assert pre_work_start(tmp_path) == []


class TestPreWorkStartAtticGuard:
    def test_not_in_attic(self, tmp_path):
        path = tmp_path / "slots" / "5" / "engine"
        assert pre_work_start_attic_guard(path) == []

    def test_in_attic(self, tmp_path):
        path = tmp_path / "slots" / "attic" / "5" / "engine"
        findings = pre_work_start_attic_guard(path)
        assert len(findings) == 1
        assert findings[0].category == "in-attic"

    def test_none_path_safe(self, tmp_path):
        assert pre_work_start_attic_guard(Path("")) == []
