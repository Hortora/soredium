"""Tests for quick-fix/quick_fix.py — commit a small change on the base branch and land it on disk."""

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


def _sha(repo, ref="HEAD"):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", ref],
                          capture_output=True, text=True).stdout.strip()


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


class TestLandsOnDisk:
    """Dirty tree on main: one commit on main, nothing sent anywhere."""

    def test_lands_dirty_tree(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        (repo / "fix.txt").write_text("fix\n")

        rc, out = _run(repo, "fix: quick change")

        assert rc == 0
        assert out["COMMITTED"] == "yes"
        assert out["LANDED"] == "yes"
        assert out["SHA"] == _sha(repo, "main")
        assert _git(repo, "status", "--porcelain").stdout == ""

    def test_commit_message_preserved(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        (repo / "fix.txt").write_text("fix\n")

        _run(repo, "fix: specific message")

        assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == "fix: specific message"

    def test_nothing_is_pushed_and_publishing_is_offered(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        remote_before = _sha(bare, "main")
        (repo / "fix.txt").write_text("fix\n")

        rc, out = _run(repo, "fix: stays on disk")

        assert rc == 0
        assert _sha(bare, "main") == remote_before
        assert out["UNPUBLISHED"] == "1"
        assert out["OFFER"] == "publish"
        assert "PUSHED" not in out and "MIRRORED" not in out

    def test_no_branch_is_created_and_the_checkout_stays_on_main(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        (repo / "fix.txt").write_text("fix\n")

        _run(repo, "fix: no ephemeral branch")

        assert _git(repo, "branch", "--format=%(refname:short)").stdout.split() == ["main"]
        assert _git(repo, "branch", "--show-current").stdout.strip() == "main"

    def test_repo_without_a_remote_lands_and_offers_nothing(self, tmp_path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "fix.txt").write_text("fix\n")

        rc, out = _run(repo, "fix: local only")

        assert rc == 0
        assert out["LANDED"] == "yes"
        assert "OFFER" not in out


class TestUnpublishedCommitsAreNormal:
    """Commits on main that the remote lacks are landed work awaiting publish, not a mistake
    to rescue. They used to be moved to a branch while main was hard-reset."""

    def _ahead(self, tmp_path):
        repo, bare = _setup_with_remote(tmp_path)
        (repo / "landed.txt").write_text("landed earlier\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "feat: landed earlier")
        return repo, bare, _sha(repo)

    def test_existing_commit_is_not_rewritten_or_moved(self, tmp_path):
        repo, bare, earlier = self._ahead(tmp_path)
        (repo / "fix.txt").write_text("fix\n")

        rc, out = _run(repo, "fix: on top")

        assert rc == 0
        assert _sha(repo, "HEAD~1") == earlier
        assert out["UNPUBLISHED"] == "2"
        assert _git(repo, "stash", "list").stdout == ""

    def test_clean_tree_has_nothing_to_do_but_says_what_is_unpublished(self, tmp_path):
        repo, bare, earlier = self._ahead(tmp_path)

        rc, out = _run(repo, "fix: nothing")

        assert rc == 1
        assert out["ERROR"] == "NOTHING_TO_DO"
        assert out["UNPUBLISHED"] == "1"
        assert out["OFFER"] == "publish"
        assert _sha(repo) == earlier
        assert _sha(bare, "main") != earlier


class TestSlotClone:
    def _slot(self, tmp_path):
        canon, bare = _setup_with_remote(tmp_path)
        slot = tmp_path / "slots" / "7"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("# Slot 7\n")
        clone = slot / "repo"
        subprocess.run(["git", "clone", "-q", str(canon), str(clone)], capture_output=True, check=True)
        _git(clone, "config", "user.name", "Test")
        _git(clone, "config", "user.email", "t@t.com")
        _git(clone, "remote", "rename", "origin", "local")
        return canon, clone, bare

    def test_fix_in_a_slot_reaches_canonical_without_touching_its_checkout(self, tmp_path):
        canon, clone, bare = self._slot(tmp_path)
        _git(canon, "checkout", "-q", "-b", "someone-elses-work")
        (canon / "wip.txt").write_text("uncommitted\n")
        (clone / "fix.txt").write_text("fix\n")

        rc, out = _run(clone, "fix: from a slot")

        assert rc == 0, out
        assert _sha(canon, "main") == _sha(clone, "main") == out["SHA"]
        assert _git(canon, "branch", "--show-current").stdout.strip() == "someone-elses-work"
        assert (canon / "wip.txt").read_text() == "uncommitted\n"
        assert _sha(bare, "main") != out["SHA"]
        assert out["UNPUBLISHED"] == "1"

    def test_canonical_moved_on_is_rebased_onto(self, tmp_path):
        canon, clone, bare = self._slot(tmp_path)
        (canon / "other.txt").write_text("landed by someone else\n")
        _git(canon, "add", ".")
        _git(canon, "commit", "-m", "feat: other")
        other = _sha(canon)
        (clone / "fix.txt").write_text("fix\n")

        rc, out = _run(clone, "fix: from a slot")

        assert rc == 0, out
        assert _sha(canon, "main~1") == other
        assert _git(canon, "rev-list", "--merges", "--count", "main").stdout.strip() == "0"


class TestErrorCases:
    def test_not_on_main(self, tmp_path):
        repo, _ = _setup_with_remote(tmp_path)
        _git(repo, "checkout", "-b", "feature")
        (repo / "fix.txt").write_text("fix\n")

        rc, out = _run(repo, "fix: wrong branch")
        assert rc == 1
        assert out["ERROR"] == "NOT_ON_MAIN"
        assert (repo / "fix.txt").read_text() == "fix\n"

    def test_nothing_to_do(self, tmp_path):
        repo, _ = _setup_with_remote(tmp_path)

        rc, out = _run(repo, "fix: nothing")
        assert rc == 1
        assert out["ERROR"] == "NOTHING_TO_DO"
        assert "OFFER" not in out

    def test_missing_message(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        assert "MISSING_MESSAGE" in result.stdout

    def test_not_a_repo(self, tmp_path):
        rc, out = _run(tmp_path, "fix: not a repo")
        assert rc == 1
        assert out["ERROR"] == "NOT_A_REPO"

    def test_operation_in_progress_is_refused_and_left_alone(self, tmp_path):
        repo, _ = _setup_with_remote(tmp_path)
        _git(repo, "checkout", "-q", "-b", "clash")
        (repo / "README.md").write_text("clash\n")
        _git(repo, "commit", "-am", "clash")
        _git(repo, "checkout", "-q", "main")
        (repo / "README.md").write_text("main side\n")
        _git(repo, "commit", "-am", "main side")
        _git(repo, "merge", "clash")
        assert (repo / ".git" / "MERGE_HEAD").exists()

        rc, out = _run(repo, "fix: during a merge")

        assert rc == 1
        assert out["ERROR"] == "BUSY"
        assert (repo / ".git" / "MERGE_HEAD").exists()

    def test_rejected_commit_changes_nothing_on_main(self, tmp_path):
        repo, _ = _setup_with_remote(tmp_path)
        hook = repo / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\necho 'no issue reference' >&2\nexit 1\n")
        hook.chmod(0o755)
        before = _sha(repo)
        (repo / "fix.txt").write_text("fix\n")

        rc, out = _run(repo, "fix: rejected")

        assert rc == 1
        assert out["ERROR"] == "COMMIT_FAILED"
        assert "no issue reference" in out["ERROR_DETAIL"]
        assert _sha(repo) == before
        assert (repo / "fix.txt").read_text() == "fix\n"
