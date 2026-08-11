"""Tests for quick-fix/quick_fix.py — ephemeral branch landing flow."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "quick-fix" / "quick_fix.py"


def _init_bare(path):
    """Create a bare repo to act as the blessed remote."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(path)], capture_output=True, check=True)


def _init_repo(path, bare_path=None):
    """Create a repo with an initial commit, optionally cloned from bare."""
    if bare_path:
        subprocess.run(["git", "clone", str(bare_path), str(path)],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"],
                       capture_output=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"],
                       capture_output=True)
        (path / "README.md").write_text("init\n")
        subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "-m", "init"],
                       capture_output=True, check=True)
        if bare_path is None:
            subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"],
                           capture_output=True)


def _setup_with_remote(tmp_path):
    """Create bare remote + cloned working repo on main."""
    bare = tmp_path / "bare.git"
    repo = tmp_path / "repo"
    _init_repo(repo)
    _init_bare(bare)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)],
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"],
                   capture_output=True, check=True)
    return repo, bare


def _run(project, message, base_branch="main"):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(project), f"message={message}",
         f"base_branch={base_branch}"],
        capture_output=True, text=True, timeout=30,
    )
    out = {}
    for line in result.stdout.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return result.returncode, out


class TestNormalFlow:
    """Dirty tree on main, no unpushed commits."""

    def test_lands_dirty_tree(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        (repo / "fix.txt").write_text("fix\n")

        rc, out = _run(repo, "fix: quick change")
        assert rc == 0
        assert out["MODE"] == "normal"
        assert out["COMMITTED"] == "yes"
        assert out["LANDED"] == "yes"
        assert out["PUSHED"] == "yes"
        assert out["CLEANED"] == "yes"

    def test_commit_message_preserved(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        (repo / "fix.txt").write_text("fix\n")

        _run(repo, "fix: specific message")
        r = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"],
                           capture_output=True, text=True)
        assert r.stdout.strip() == "fix: specific message"

    def test_ephemeral_branch_deleted(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        (repo / "fix.txt").write_text("fix\n")

        _run(repo, "fix: cleanup test")
        r = subprocess.run(["git", "-C", str(repo), "branch"],
                           capture_output=True, text=True)
        assert "quick-" not in r.stdout

    def test_pushed_to_remote(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        (repo / "fix.txt").write_text("fix\n")

        _run(repo, "fix: push test")
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True)
        local_sha = r.stdout.strip()
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "origin/main"],
                           capture_output=True, text=True)
        remote_sha = r.stdout.strip()
        assert local_sha == remote_sha


class TestRescueFlow:
    """Commits already on main ahead of remote."""

    def test_rescues_unpushed_commit(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)

        (repo / "committed.txt").write_text("already committed\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "direct commit"],
                       capture_output=True)

        rc, out = _run(repo, "fix: rescue test")
        assert rc == 0
        assert out["MODE"] == "rescue"
        assert out["LANDED"] == "yes"
        assert out["PUSHED"] == "yes"

    def test_rescue_preserves_commit_content(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)

        (repo / "important.txt").write_text("must not lose this\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "important work"],
                       capture_output=True)

        _run(repo, "fix: rescue")
        assert (repo / "important.txt").exists()
        assert (repo / "important.txt").read_text() == "must not lose this\n"

    def test_rescue_with_dirty_tree(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)

        (repo / "committed.txt").write_text("committed\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "direct commit"],
                       capture_output=True)
        (repo / "uncommitted.txt").write_text("also this\n")

        rc, out = _run(repo, "fix: rescue with dirty")
        assert rc == 0
        assert out["MODE"] == "rescue"
        assert out["COMMITTED"] == "yes"
        assert out["LANDED"] == "yes"
        assert (repo / "uncommitted.txt").exists()


class TestErrorCases:
    def test_not_on_main(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feature"],
                       capture_output=True)

        rc, out = _run(repo, "fix: should fail")
        assert rc == 1
        assert out["ERROR"] == "NOT_ON_MAIN"

    def test_nothing_to_do(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)

        rc, out = _run(repo, "fix: nothing")
        assert rc == 1
        assert out["ERROR"] == "NOTHING_TO_DO"

    def test_missing_message(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(repo)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_not_a_repo(self, tmp_path):
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        rc, out = _run(plain, "fix: not a repo")
        assert rc == 1
        assert out["ERROR"] == "NOT_A_REPO"


class TestTopology:
    """Fork vs direct remote topology."""

    def test_fork_model_pushes_to_upstream(self, tmp_path):
        """With upstream remote, push goes to upstream (blessed), mirror to origin (fork)."""
        blessed = tmp_path / "blessed.git"
        fork = tmp_path / "fork.git"
        repo = tmp_path / "repo"

        _init_bare(blessed)
        _init_bare(fork)
        _init_repo(repo)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(fork)],
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "upstream", str(blessed)],
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "push", "origin", "main"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "push", "upstream", "main"],
                       capture_output=True, check=True)

        (repo / "fix.txt").write_text("fork fix\n")
        rc, out = _run(repo, "fix: fork model test")
        assert rc == 0
        assert out["PUSHED"] == "yes"
        assert out["MIRRORED"] == "yes"

    def test_direct_model_no_mirror(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        (repo / "fix.txt").write_text("direct fix\n")

        rc, out = _run(repo, "fix: direct model test")
        assert rc == 0
        assert out["PUSHED"] == "yes"
        assert out["MIRRORED"] == "na"
