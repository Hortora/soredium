"""Tests for work-end/work_end_context.py"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "work-end" / "work_end_context.py"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("init\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial commit")
    return path


def _create_project_with_branch(
    tmp_path: Path, branch: str = "issue-99-test",
) -> tuple[Path, Path]:
    """Create workspace + project on a feature branch with .meta."""
    workspace = _init_repo(tmp_path / "workspace")
    project = _init_repo(tmp_path / "project")

    _git(workspace, "checkout", "-b", branch)
    design = workspace / "design"
    design.mkdir(exist_ok=True)
    meta = design / ".meta"
    meta.write_text(
        f"branch: {branch}\n"
        f"issue: 99\n"
        f"issue-repo: Test/repo\n"
        f"covers: 99\n"
        f"project-sha: abc123\n"
        f"date: 2026-08-05\n"
        f"state: active\n"
        f"design-repo: workspace\n"
    )
    _git(workspace, "add", "design/.meta")
    _git(workspace, "commit", "-m", "scaffold")

    _git(project, "checkout", "-b", branch)
    return workspace, project


def _run_context(
    workspace: Path, project: Path, **extra: str,
) -> subprocess.CompletedProcess:
    args = [
        sys.executable, str(SCRIPT),
        f"workspace={workspace}", f"project={project}",
    ]
    for k, v in extra.items():
        args.append(f"{k}={v}")
    return subprocess.run(args, capture_output=True, text=True, timeout=15)


class TestContextCleanState:
    def test_clean_state_passes_preconditions(self, tmp_path: Path) -> None:
        workspace, project = _create_project_with_branch(tmp_path)
        result = _run_context(workspace, project)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["preconditions"]["clean_tree"]["status"] == "pass"
        assert data["preconditions"]["meta_exists"]["status"] == "pass"
        assert data["context"]["workspace"] == str(workspace)
        assert data["context"]["project"] == str(project)

    def test_context_includes_branch(self, tmp_path: Path) -> None:
        workspace, project = _create_project_with_branch(tmp_path)
        result = _run_context(workspace, project)
        data = json.loads(result.stdout)
        assert data["context"]["branch"] == "issue-99-test"


class TestContextDirtyTree:
    def test_dirty_workspace(self, tmp_path: Path) -> None:
        workspace, project = _create_project_with_branch(tmp_path)
        (workspace / "dirty.txt").write_text("uncommitted\n")

        result = _run_context(workspace, project)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["preconditions"]["clean_tree"]["status"] == "fail"

    def test_dirty_project(self, tmp_path: Path) -> None:
        workspace, project = _create_project_with_branch(tmp_path)
        (project / "dirty.txt").write_text("uncommitted\n")

        result = _run_context(workspace, project)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["preconditions"]["clean_tree"]["status"] == "fail"


class TestContextNoMeta:
    def test_missing_meta(self, tmp_path: Path) -> None:
        workspace = _init_repo(tmp_path / "workspace")
        project = _init_repo(tmp_path / "project")
        _git(workspace, "checkout", "-b", "issue-50-test")
        _git(project, "checkout", "-b", "issue-50-test")

        result = _run_context(workspace, project)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["preconditions"]["meta_exists"]["status"] == "needs_input"


class TestContextBadArgs:
    def test_missing_args(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
