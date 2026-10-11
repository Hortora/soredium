"""Tests for verification/close_verify.py — composed verifier."""

import subprocess
from pathlib import Path

from verification.close_verify import verify, _is_blocking
from verification import Finding


def _git(path: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(path)] + list(args),
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
    _git(path, "commit", "-m", "initial")
    return path


def _init_repo_with_remote(tmp_path: Path, name: str = "repo") -> Path:
    bare = tmp_path / f"{name}-bare.git"
    bare.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    repo = _init_repo(tmp_path / name)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")
    return repo


def _do_work_and_close(project: Path, workspace: Path, branch: str = "feature"):
    for repo in [project, workspace]:
        _git(repo, "checkout", "-b", branch)
        (repo / "work.txt").write_text("work\n")
        _git(repo, "add", "work.txt")
        _git(repo, "commit", "-m", "feat: work")

    for repo in [project, workspace]:
        _git(repo, "checkout", "main")
        _git(repo, "merge", branch, "--no-ff", "-m", "merge")
        _git(repo, "push", "origin", "main")
        sha = _git(repo, "rev-parse", "main")
        _git(repo, "checkout", branch)
        _git(repo, "commit", "--allow-empty",
             "-m", f"chore: branch closed — landed as {sha} on main")
        _git(repo, "checkout", "main")


class TestIsBlocking:
    def test_blocking_category(self):
        findings = [Finding("ERROR", "branch-not-merged", "test")]
        assert _is_blocking("project_merged", findings) is True

    def test_non_blocking_warning(self):
        findings = [Finding("WARN", "stale-scaffold", "test")]
        assert _is_blocking("no_stale_scaffold", findings) is False

    def test_canonical_sync_blocking(self):
        findings = [Finding("ERROR", "canonical-sync", "test")]
        assert _is_blocking("canonical_sync_myrepo", findings) is True

    def test_empty_findings_not_blocking(self):
        assert _is_blocking("anything", []) is False


class TestVerifyOnMain:
    def test_clean_on_main(self, tmp_path):
        project = _init_repo_with_remote(tmp_path / "proj-parent", "project")
        workspace = _init_repo_with_remote(tmp_path / "ws-parent", "workspace")
        result = verify(project, "feature", workspace, on_main=True)
        assert result is True


class TestVerifyBranch:
    def test_clean_close(self, tmp_path, capsys):
        project = _init_repo_with_remote(tmp_path / "proj-parent", "project")
        workspace = _init_repo_with_remote(tmp_path / "ws-parent", "workspace")
        _do_work_and_close(project, workspace, "feature")
        (workspace / ".artifacts-promoted").write_text("done\n")
        result = verify(project, "feature", workspace)
        captured = capsys.readouterr()
        assert "VERIFIED=yes" in captured.out
        assert result is True

    def test_unmerged_branch(self, tmp_path, capsys):
        project = _init_repo_with_remote(tmp_path / "proj-parent", "project")
        workspace = _init_repo_with_remote(tmp_path / "ws-parent", "workspace")
        _git(project, "checkout", "-b", "feature")
        (project / "work.txt").write_text("work\n")
        _git(project, "add", "work.txt")
        _git(project, "commit", "-m", "feat: unmerged")
        _git(workspace, "checkout", "-b", "feature")
        _git(workspace, "commit", "--allow-empty", "-m", "feat: ws")
        result = verify(project, "feature", workspace)
        captured = capsys.readouterr()
        assert "VERIFIED=no" in captured.out
        assert result is False
