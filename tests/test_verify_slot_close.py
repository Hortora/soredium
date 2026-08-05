"""Tests for work-end/verify_slot_close.py"""

import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "work-end" / "verify_slot_close.py"


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


def _create_clean_single_repo(tmp_path: Path, branch: str = "issue-99-test") -> tuple[Path, Path]:
    """Create a project repo with branch merged, stamped, and pushed."""
    remote = _init_bare(tmp_path / "remote.git")
    project = _init_repo(tmp_path / "project")
    _git(project, "remote", "add", "origin", str(remote))
    _git(project, "push", "origin", "main")

    _git(project, "checkout", "-b", branch)
    (project / "feature.txt").write_text("feature\n")
    _git(project, "add", "feature.txt")
    _git(project, "commit", "-m", "feat: add feature")
    _git(project, "push", "origin", branch)

    _git(project, "checkout", "main")
    _git(project, "merge", "--ff-only", branch)
    _git(project, "push", "origin", "main")

    sha = _git(project, "rev-parse", "main")
    _git(project, "checkout", branch)
    _git(project, "commit", "--allow-empty", "-m",
         f"chore: branch closed — landed as {sha} on main")
    _git(project, "push", "origin", branch, "--force-with-lease")
    _git(project, "checkout", "main")

    workspace = _init_repo(tmp_path / "workspace")
    _git(workspace, "checkout", "-b", branch)
    _git(workspace, "commit", "--allow-empty", "-m",
         f"chore: branch closed — landed as {sha} on main")
    _git(workspace, "checkout", "main")

    return project, workspace


def _run_verify(
    project: Path, workspace: Path, branch: str = "issue-99-test",
    **extra_args: str,
) -> subprocess.CompletedProcess:
    args = [
        sys.executable, str(SCRIPT),
        str(project), f"branch={branch}", f"workspace={workspace}",
    ]
    for k, v in extra_args.items():
        args.append(f"{k}={v}")
    return subprocess.run(args, capture_output=True, text=True)


class TestVerifyAllPass:
    def test_single_repo_clean_state(self, tmp_path: Path) -> None:
        project, workspace = _create_clean_single_repo(tmp_path)
        result = _run_verify(project, workspace)
        assert result.returncode == 0
        assert "VERIFIED=yes" in result.stdout


class TestVerifyMissingStamp:
    def test_unstamped_branch(self, tmp_path: Path) -> None:
        branch = "issue-100-test"
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "f.txt").write_text("work\n")
        _git(project, "add", "f.txt")
        _git(project, "commit", "-m", "feat: work")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)
        _git(project, "push", "origin", "main")

        workspace = _init_repo(tmp_path / "workspace")

        result = _run_verify(project, workspace, branch=branch)
        assert "VERIFIED=no" in result.stdout
        assert "UNSTAMPED" in result.stdout


class TestVerifyUnpushedMain:
    def test_local_ahead_of_origin(self, tmp_path: Path) -> None:
        branch = "issue-101-test"
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "f.txt").write_text("work\n")
        _git(project, "add", "f.txt")
        _git(project, "commit", "-m", "feat: work")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)
        # Deliberately do NOT push main

        sha = _git(project, "rev-parse", "main")
        _git(project, "checkout", branch)
        _git(project, "commit", "--allow-empty", "-m",
             f"chore: branch closed — landed as {sha} on main")
        _git(project, "checkout", "main")

        workspace = _init_repo(tmp_path / "workspace")

        result = _run_verify(project, workspace, branch=branch)
        assert "VERIFIED=no" in result.stdout
        assert "UNPUSHED" in result.stdout


class TestVerifyBadArgs:
    def test_missing_args(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
