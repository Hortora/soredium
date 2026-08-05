"""Tests for work-end/work_end_execute.py"""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "work-end" / "work_end_execute.py"


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


def _init_bare(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(path)], capture_output=True, check=True)
    return path


def _run_execute(
    subcommand: str, *extra_args: str,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), subcommand, *extra_args],
        capture_output=True, text=True, timeout=30,
    )


class TestPromoteSingleRepo:
    def test_promote_writes_progress(self, tmp_path: Path) -> None:
        workspace = _init_repo(tmp_path / "workspace")
        project = _init_repo(tmp_path / "project")
        branch = "issue-99-test"

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        _git(project, "checkout", "-b", branch)

        result = _run_execute(
            "promote",
            f"workspace={workspace}",
            f"project={project}",
            f"branch={branch}",
        )
        assert result.returncode == 0
        assert "PROMOTED=yes" in result.stdout

        progress_path = design / ".execute-progress"
        assert progress_path.exists()
        content = progress_path.read_text()
        assert "promoted" in content

    def test_promote_skips_already_promoted(self, tmp_path: Path) -> None:
        workspace = _init_repo(tmp_path / "workspace")
        project = _init_repo(tmp_path / "project")
        branch = "issue-100-test"

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        (design / ".execute-progress").write_text("default=promoted\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        _git(project, "checkout", "-b", branch)

        result = _run_execute(
            "promote",
            f"workspace={workspace}",
            f"project={project}",
            f"branch={branch}",
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout or "already" in result.stdout.lower()


class TestRebaseSingleRepo:
    def test_rebase_onto_base(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-101-test")
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: feature")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-101-test",
            "base_branch=main",
        )
        assert result.returncode == 0
        assert "REBASED=yes" in result.stdout

    def test_rebase_conflict_reports_error(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-102-test")
        (project / "README.md").write_text("branch version\n")
        _git(project, "add", "README.md")
        _git(project, "commit", "-m", "feat: branch change")

        _git(project, "checkout", "main")
        (project / "README.md").write_text("main version\n")
        _git(project, "add", "README.md")
        _git(project, "commit", "-m", "fix: main change")

        _git(project, "checkout", "issue-102-test")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-102-test",
            "base_branch=main",
        )
        assert "ERROR=REBASE_CONFLICT" in result.stdout


class TestBadArgs:
    def test_missing_subcommand(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_unknown_subcommand(self) -> None:
        result = _run_execute("unknown")
        assert result.returncode == 1
        assert "ERROR" in result.stdout
