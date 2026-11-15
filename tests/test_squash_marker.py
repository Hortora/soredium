"""Tests for project/squash_marker.py — the squash-review marker bound to a branch tip."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from squash_marker import clear, mark, marker_ref, review_status  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "commit", "--allow-empty", "-m", "init")
    return path


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", f"feat: add {name} Refs #1")
    return _git(repo, "rev-parse", "HEAD")


def _branch(repo: Path, branch: str, commits: int) -> str:
    _git(repo, "checkout", "-b", branch)
    tip = ""
    for i in range(commits):
        tip = _commit(repo, f"{branch.replace('/', '_')}-{i}.txt")
    return tip


class TestReviewStatus:

    def test_single_commit_needs_no_review(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat", 1)
        assert review_status(repo, "feat", "main") is None

    def test_several_commits_without_marker(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat", 3)
        reason = review_status(repo, "feat", "main")
        assert reason is not None
        assert "no squash review" in reason
        assert "3" in reason

    def test_marker_at_tip_is_cleared_to_land(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat", 3)
        mark(repo, "feat")
        assert review_status(repo, "feat", "main") is None

    def test_commits_added_after_review(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat", 2)
        mark(repo, "feat")
        _commit(repo, "late-1.txt")
        _commit(repo, "late-2.txt")
        reason = review_status(repo, "feat", "main")
        assert reason is not None
        assert "2 commit(s) added since" in reason

    def test_branch_rebased_after_review(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat", 2)
        mark(repo, "feat")
        _git(repo, "checkout", "main")
        _commit(repo, "main-moved.txt")
        _git(repo, "checkout", "feat")
        _git(repo, "rebase", "main")
        reason = review_status(repo, "feat", "main")
        assert reason is not None
        assert "not part of this branch" in reason

    def test_marker_from_another_branch_name_is_not_used(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat-a", 2)
        mark(repo, "feat-a")
        _git(repo, "checkout", "main")
        _branch(repo, "feat-b", 2)
        reason = review_status(repo, "feat-b", "main")
        assert reason is not None
        assert "no squash review" in reason


class TestMark:

    def test_mark_records_the_branch_tip(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        tip = _branch(repo, "feat", 2)
        assert mark(repo, "feat") == tip
        assert _git(repo, "rev-parse", marker_ref("feat")) == tip

    def test_mark_defaults_to_current_branch(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        tip = _branch(repo, "feat", 2)
        assert mark(repo) == tip
        assert _git(repo, "rev-parse", marker_ref("feat")) == tip

    def test_mark_leaves_working_tree_and_history_untouched(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        tip = _branch(repo, "feat", 2)
        mark(repo, "feat")
        assert _git(repo, "status", "--porcelain") == ""
        assert _git(repo, "rev-parse", "feat") == tip

    def test_mark_unknown_branch_raises(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        with pytest.raises(RuntimeError, match="does not exist"):
            mark(repo, "no-such-branch")

    def test_mark_on_detached_head_without_branch_raises(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "--detach")
        with pytest.raises(RuntimeError, match="no branch"):
            mark(repo)

    def test_branch_names_with_slashes(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        tip = _branch(repo, "fix/549-thing", 2)
        mark(repo, "fix/549-thing")
        assert _git(repo, "rev-parse", marker_ref("fix/549-thing")) == tip
        assert review_status(repo, "fix/549-thing", "main") is None


class TestClear:

    def test_clear_removes_marker(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat", 2)
        mark(repo, "feat")
        clear(repo, "feat")
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q",
                            marker_ref("feat")], capture_output=True)
        assert r.returncode != 0

    def test_clear_without_marker_is_a_noop(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat", 2)
        clear(repo, "feat")


class TestCli:

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        script = Path(__file__).parent.parent / "project" / "squash_marker.py"
        return subprocess.run([sys.executable, str(script), *args],
                              capture_output=True, text=True)

    def test_mark_command(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        tip = _branch(repo, "feat", 2)
        r = self._run("mark", str(repo))
        assert r.returncode == 0, r.stderr
        assert f"MARKED={tip}" in r.stdout
        assert "BRANCH=feat" in r.stdout

    def test_status_command_reports_review_needed(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat", 2)
        r = self._run("status", str(repo), "branch=feat", "base=main")
        assert r.returncode == 0, r.stderr
        assert "REVIEW_NEEDED=yes" in r.stdout
        assert "REASON=" in r.stdout

    def test_status_command_reports_clear(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _branch(repo, "feat", 2)
        self._run("mark", str(repo))
        r = self._run("status", str(repo), "branch=feat", "base=main")
        assert "REVIEW_NEEDED=no" in r.stdout

    def test_unknown_command_fails(self, tmp_path):
        r = self._run("frobnicate", str(tmp_path))
        assert r.returncode != 0
