"""Tests for #342: .plan in project repo detection, prevention, and recovery."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-start"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


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


class TestCheckPlanInProject:
    """Layer 1: verification/repo_checks.check_plan_in_project"""

    def test_no_plan_no_finding(self, tmp_path):
        from verification.repo_checks import check_plan_in_project
        project = _init_repo(tmp_path / "project")
        assert check_plan_in_project(project) == []

    def test_plan_without_wksp_ok(self, tmp_path):
        """No workspace → .plan in project is fine (single-repo mode)."""
        from verification.repo_checks import check_plan_in_project
        project = _init_repo(tmp_path / "project")
        (project / ".plan").write_text("branch: issue-42\nstate: active\n")
        assert check_plan_in_project(project) == []

    def test_plan_with_wksp_error(self, tmp_path):
        """Workspace exists → .plan in project is wrong."""
        from verification.repo_checks import check_plan_in_project
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(str(workspace))
        (project / ".plan").write_text("branch: issue-42\nstate: active\n")
        findings = check_plan_in_project(project)
        assert len(findings) == 1
        assert findings[0].category == "plan-in-project"
        assert findings[0].severity == "ERROR"


class TestScaffoldValidation:
    """Layer 2: scaffold.py refuses to write .plan to a project repo."""

    def test_scaffold_in_workspace_ok(self, tmp_path):
        from scaffold import scaffold
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "proj").symlink_to(str(tmp_path))
        result = scaffold(
            workspace=workspace, branch="issue-42-test",
            project_sha="abc123", issue="42", issue_repo="Hortora/soredium",
            force=True,
        )
        assert result.created
        assert (workspace / ".plan").exists()

    def test_scaffold_in_project_with_wksp_raises(self, tmp_path):
        """Project repo with wksp/ but no proj/ → should be rejected."""
        from scaffold import scaffold
        project = tmp_path / "project"
        project.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (project / "wksp").symlink_to(str(workspace))
        with pytest.raises(OSError, match="looks like a project repo"):
            scaffold(
                workspace=project, branch="issue-42-test",
                project_sha="abc123", issue="42", force=True,
            )

    def test_scaffold_in_dir_with_both_symlinks_ok(self, tmp_path):
        """Dir with both wksp/ and proj/ is ambiguous — allow (workspace-in-slot pattern)."""
        from scaffold import scaffold
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "wksp").symlink_to(str(tmp_path))
        (workspace / "proj").symlink_to(str(tmp_path))
        result = scaffold(
            workspace=workspace, branch="issue-42-test",
            project_sha="abc123", force=True,
        )
        assert result.created

    def test_scaffold_with_workspace_marker_ok(self, tmp_path):
        """Dir with wksp/ but .workspace marker → it's a workspace clone, allow."""
        from scaffold import scaffold
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "wksp").symlink_to(str(tmp_path))
        (workspace / ".workspace").touch()
        result = scaffold(
            workspace=workspace, branch="issue-42-test",
            project_sha="abc123", force=True,
        )
        assert result.created

    def test_scaffold_plain_dir_ok(self, tmp_path):
        """Dir without any symlinks → allow (fresh workspace setup)."""
        from scaffold import scaffold
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = scaffold(
            workspace=workspace, branch="issue-42-test",
            project_sha="abc123", force=True,
        )
        assert result.created


class TestCorruptionDetection:
    """Layer 3: corruption.py detects orphaned .plan in project repo."""

    def test_no_plan_no_finding(self, tmp_path):
        from corruption import _check_plan_in_project
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        assert _check_plan_in_project(project, workspace) is None

    def test_plan_in_project_with_workspace(self, tmp_path):
        from corruption import _check_plan_in_project
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(str(workspace))
        (project / ".plan").write_text("branch: issue-42\nstate: active\n")
        result = _check_plan_in_project(project, workspace)
        assert result is not None
        assert result.scenario == "S12_PLAN_IN_PROJECT"
        assert "move_plan" in result.actions

    def test_plan_without_wksp_no_finding(self, tmp_path):
        from corruption import _check_plan_in_project
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        (project / ".plan").write_text("branch: issue-42\nstate: active\n")
        assert _check_plan_in_project(project, workspace) is None
