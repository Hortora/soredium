"""Tests for verification/repo_checks.py"""

import subprocess
from pathlib import Path

from verification.repo_checks import (
    check_conflict_markers_on_remote,
    check_duplicate_commits,
    check_stuck_close_state,
    check_unpushed_main,
    check_workspace_wipe,
)


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


class TestCheckUnpushedMain:
    def test_clean_main(self, tmp_path):
        repo = _init_repo_with_remote(tmp_path)
        findings = check_unpushed_main(repo)
        assert findings == []

    def test_unpushed_commits(self, tmp_path):
        repo = _init_repo_with_remote(tmp_path)
        (repo / "new.txt").write_text("new\n")
        _git(repo, "add", "new.txt")
        _git(repo, "commit", "-m", "unpushed change")
        findings = check_unpushed_main(repo)
        assert any(f.category == "unpushed-main" for f in findings)

    def test_on_feature_branch_skipped(self, tmp_path):
        repo = _init_repo_with_remote(tmp_path)
        _git(repo, "checkout", "-b", "feature")
        assert check_unpushed_main(repo) == []

    def test_dirty_main(self, tmp_path):
        repo = _init_repo_with_remote(tmp_path)
        (repo / "untracked.txt").write_text("dirty\n")
        findings = check_unpushed_main(repo)
        assert any(f.category == "dirty-main" for f in findings)

    def test_nonexistent_repo(self, tmp_path):
        assert check_unpushed_main(tmp_path / "missing") == []


class TestCheckWorkspaceWipe:
    def test_clean_workspace(self, tmp_path):
        repo = _init_repo(tmp_path / "ws")
        assert check_workspace_wipe(repo) == []

    def test_few_deletions_ok(self, tmp_path):
        repo = _init_repo(tmp_path / "ws")
        for i in range(5):
            (repo / f"file{i}.md").write_text(f"content {i}\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add files")
        for i in range(5):
            (repo / f"file{i}.md").unlink()
        findings = check_workspace_wipe(repo)
        assert findings == []

    def test_bulk_deletions_detected(self, tmp_path):
        repo = _init_repo(tmp_path / "ws")
        for i in range(15):
            (repo / f"file{i}.md").write_text(f"content {i}\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add files")
        for i in range(15):
            (repo / f"file{i}.md").unlink()
        findings = check_workspace_wipe(repo)
        assert len(findings) == 1
        assert findings[0].category == "workspace-wipe"

    def test_nonexistent_workspace(self, tmp_path):
        assert check_workspace_wipe(tmp_path / "missing") == []


class TestCheckStuckCloseState:
    def test_active_state_ok(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("state: active\nbranch: issue-42\n")
        assert check_stuck_close_state(plan) == []

    def test_closing_state_detected(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("state: closing:review\nbranch: issue-42\n")
        findings = check_stuck_close_state(plan)
        assert len(findings) == 1
        assert findings[0].category == "stuck-close"

    def test_no_plan(self, tmp_path):
        assert check_stuck_close_state(tmp_path / ".plan") == []

    def test_state_without_closing(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("state: drained\nbranch: issue-42\n")
        assert check_stuck_close_state(plan) == []


class TestCheckDuplicateCommits:
    def test_no_duplicates(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        (repo / "a.txt").write_text("a\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "feat: add a")
        (repo / "b.txt").write_text("b\n")
        _git(repo, "add", "b.txt")
        _git(repo, "commit", "-m", "feat: add b")
        assert check_duplicate_commits(repo) == []

    def test_duplicate_detected(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        (repo / "a.txt").write_text("a\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "feat: add feature")
        (repo / "b.txt").write_text("b\n")
        _git(repo, "add", "b.txt")
        _git(repo, "commit", "-m", "feat: add feature")
        findings = check_duplicate_commits(repo)
        assert len(findings) == 1
        assert findings[0].category == "duplicate-commit"

    def test_mechanical_prefixes_skipped(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "commit", "--allow-empty", "-m", "chore: branch closed — landed as abc")
        _git(repo, "commit", "--allow-empty", "-m", "chore: branch closed — landed as def")
        assert check_duplicate_commits(repo) == []

    def test_nonexistent_repo(self, tmp_path):
        assert check_duplicate_commits(tmp_path / "missing") == []


class TestCheckConflictMarkers:
    def test_clean_repo(self, tmp_path):
        repo = _init_repo_with_remote(tmp_path)
        assert check_conflict_markers_on_remote(repo, "origin") == []

    def test_nonexistent_repo(self, tmp_path):
        assert check_conflict_markers_on_remote(tmp_path / "missing") == []
