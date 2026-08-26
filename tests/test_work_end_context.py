"""Tests for work-end/work_end_context.py"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPT = Path(__file__).parent.parent / "work-end" / "work_end_context.py"

work_end_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(work_end_dir))
import work_end_context


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
    """Create workspace + project on a feature branch with .plan."""
    workspace = _init_repo(tmp_path / "workspace")
    project = _init_repo(tmp_path / "project")

    _git(workspace, "checkout", "-b", branch)
    plan = workspace / ".plan"
    plan.write_text(
        f"# Work Plan — {branch}\n\n"
        f"## State\n"
        f"branch: {branch}\n"
        f"state: active\n"
        f"project-sha: abc123\n"
        f"date: 2026-08-05\n"
        f"issue-repo: Test/repo\n"
        f"covers: 99\n"
        f"design-repo: workspace\n\n"
        f"## Queue\n"
        f"- [ ] #99 — Test issue ← active\n"
    )
    _git(workspace, "add", ".plan")
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


class TestStalePlan:
    """Stale .plan from a different branch is detected."""

    def test_stale_plan_detected(self, tmp_path: Path) -> None:
        workspace = _init_repo(tmp_path / "workspace")
        project = _init_repo(tmp_path / "project")
        _git(workspace, "checkout", "-b", "issue-988-bugfix")
        _git(project, "checkout", "-b", "issue-988-bugfix")
        plan = workspace / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: issue-364-old-branch\n"
            "state: active\n"
            "covers: 364\n"
        )
        _git(workspace, "add", ".plan")
        _git(workspace, "commit", "-m", "stale plan")

        result = _run_context(workspace, project)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["preconditions"]["meta_exists"]["status"] == "needs_input"
        assert data["preconditions"]["meta_exists"]["detail"] == "stale-plan"

    def test_stale_plan_infers_issue_from_branch(self, tmp_path: Path) -> None:
        workspace = _init_repo(tmp_path / "workspace")
        project = _init_repo(tmp_path / "project")
        _git(workspace, "checkout", "-b", "issue-988-bugfix")
        _git(project, "checkout", "-b", "issue-988-bugfix")
        plan = workspace / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: issue-364-old-branch\n"
            "state: active\n"
            "covers: 364\n"
        )
        _git(workspace, "add", ".plan")
        _git(workspace, "commit", "-m", "stale plan")

        result = _run_context(workspace, project)
        data = json.loads(result.stdout)
        assert data["context"]["issue"] == "988"

    def test_matching_plan_passes(self, tmp_path: Path) -> None:
        workspace, project = _create_project_with_branch(tmp_path, "issue-99-test")
        result = _run_context(workspace, project)
        data = json.loads(result.stdout)
        assert data["preconditions"]["meta_exists"]["status"] == "pass"


class TestSubdirectoryDirtyTree:
    """git status must be scoped to the workspace subdir, not the whole repo."""

    def test_sibling_dir_dirty_does_not_affect_workspace(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "t@t.com")
        _git(repo, "config", "user.name", "Test")

        ws = repo / "workspace"
        sibling = repo / "sibling"
        ws.mkdir()
        sibling.mkdir()
        (ws / "README.md").write_text("ws\n")
        (sibling / "README.md").write_text("sibling\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")

        project = _init_repo(tmp_path / "project")

        # Make sibling dirty — should NOT affect workspace status
        (sibling / "dirty.txt").write_text("uncommitted\n")

        result = _run_context(ws, project)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["preconditions"]["clean_tree"]["status"] == "pass"

    def test_workspace_subdir_dirty_is_detected(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "t@t.com")
        _git(repo, "config", "user.name", "Test")

        ws = repo / "workspace"
        ws.mkdir()
        (ws / "README.md").write_text("ws\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")

        project = _init_repo(tmp_path / "project")

        # Make workspace itself dirty — should be detected
        (ws / "dirty.txt").write_text("uncommitted\n")

        result = _run_context(ws, project)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["preconditions"]["clean_tree"]["status"] == "fail"


class TestContextBadArgs:
    def test_missing_args(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


class TestIsxStaleness:
    def test_non_slot_skipped(self, tmp_path: Path) -> None:
        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")
        result = work_end_context.check_isx_staleness(str(ws), str(proj))
        assert result["status"] == "skip"

    def test_non_isx_slot_skipped(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        proj = _init_repo(slot_dir / "engine")
        ws = _init_repo(slot_dir / "workspace")
        (slot_dir / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        result = work_end_context.check_isx_staleness(str(ws), str(proj))
        assert result["status"] == "skip"

    def test_isx_in_sync(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        proj = _init_repo(slot_dir / "engine")
        ws = _init_repo(slot_dir / "workspace")
        (slot_dir / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: test-inst\n"
            "template: tpl-java\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        sha = "abc123def456"
        def mock_git(repo, *args):
            r = MagicMock()
            r.returncode = 0
            if "rev-parse" in args:
                r.stdout = sha
            elif "ls-remote" in args:
                r.stdout = f"{sha}\tHEAD"
            return r
        with patch.object(work_end_context, "git", side_effect=mock_git):
            result = work_end_context.check_isx_staleness(str(ws), str(proj))
        assert result["status"] == "pass"

    def test_isx_stale_detected(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        proj = _init_repo(slot_dir / "engine")
        ws = _init_repo(slot_dir / "workspace")
        (slot_dir / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: test-inst\n"
            "template: tpl-java\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        def mock_git(repo, *args):
            r = MagicMock()
            r.returncode = 0
            if "rev-parse" in args:
                r.stdout = "local111"
            elif "ls-remote" in args:
                r.stdout = "remote222\tHEAD"
            return r
        with patch.object(work_end_context, "git", side_effect=mock_git):
            result = work_end_context.check_isx_staleness(str(ws), str(proj))
        assert result["status"] == "needs_input"
        assert result["detail"] == "isx-stale"
        assert "engine" in result["repos"]

    def test_isx_remote_unreachable_skips(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        proj = _init_repo(slot_dir / "engine")
        ws = _init_repo(slot_dir / "workspace")
        (slot_dir / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: test-inst\n"
            "template: tpl-java\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        def mock_git(repo, *args):
            r = MagicMock()
            if "rev-parse" in args:
                r.returncode = 0
                r.stdout = "local111"
            elif "ls-remote" in args:
                r.returncode = 1
                r.stdout = ""
            return r
        with patch.object(work_end_context, "git", side_effect=mock_git):
            result = work_end_context.check_isx_staleness(str(ws), str(proj))
        assert result["status"] == "pass"
