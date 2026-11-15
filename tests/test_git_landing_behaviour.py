"""Characterisation tests: how git behaves when a branch is landed into a canonical repo.

The canonical-sync design (#515) relies on these behaviours. They are tests of git,
not of soredium code, so a git upgrade that changes one of them fails here first.

Every command runs with global and system git config disabled, so user hooks and
settings cannot change the outcome.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_CONFIG_NOSYSTEM="1",
    GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@t",
    GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@t",
)
TRACKED = ("a.txt", "b.txt", "c.txt", "u.txt")
FETCH_THEN_FF = (("fetch", "slot", "feat"), ("merge", "--ff-only", "FETCH_HEAD"))


def run(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, env=ENV)


def g(repo: Path, *args: str, must: bool = True) -> subprocess.CompletedProcess:
    r = run("git", "-C", str(repo), *args)
    if must and r.returncode != 0:
        raise RuntimeError(f"setup failed: git {' '.join(args)}\n{r.stderr}")
    return r


def commit(repo: Path, files: dict[str, str], msg: str) -> None:
    for name, content in files.items():
        (repo / name).write_text(content)
    g(repo, "add", "-A")
    g(repo, "commit", "-q", "-m", msg)


def sha(repo: Path, ref: str) -> str:
    return g(repo, "rev-parse", "--verify", "-q", ref, must=False).stdout.strip()


@dataclass
class State:
    main: str
    head: str
    status: str
    files: dict[str, str | None]


def snapshot(repo: Path) -> State:
    head = g(repo, "symbolic-ref", "-q", "--short", "HEAD", must=False).stdout.strip() or "DETACHED"
    files = {n: ((repo / n).read_text() if (repo / n).exists() else None) for n in TRACKED}
    return State(sha(repo, "refs/heads/main"), head, g(repo, "status", "--porcelain").stdout, files)


@dataclass
class Fixture:
    canon: Path
    slot: Path
    feat: str


def build(root: Path, pre_clone=None) -> Fixture:
    """Canonical with a.txt and b.txt on main; slot is a --shared clone with branch feat."""
    canon = root / "canon"
    canon.mkdir()
    g(canon, "init", "-q", "-b", "main")
    commit(canon, {"a.txt": "a1\n", "b.txt": "b1\n"}, "init")
    if pre_clone:
        pre_clone(canon)
    slot = root / "slot"
    assert run("git", "clone", "-q", "--shared", str(canon), str(slot)).returncode == 0
    g(slot, "checkout", "-q", "-b", "feat", "origin/main")
    commit(slot, {"a.txt": "a2\n", "c.txt": "c1\n"}, "feat: change a, add c")
    commit(slot, {"d.txt": "d1\n"}, "feat: add d")
    g(canon, "remote", "add", "slot", str(slot))
    return Fixture(canon, slot, sha(slot, "feat"))


def attempt(repo: Path, steps) -> subprocess.CompletedProcess:
    result = None
    for step in steps:
        result = g(repo, *step, must=False)
        if result.returncode != 0:
            break
    return result


# --- canonical states ---

def other_branch_clean(canon: Path) -> None:
    g(canon, "checkout", "-q", "-b", "work")


def other_branch_dirty(canon: Path) -> None:
    g(canon, "checkout", "-q", "-b", "work")
    (canon / "a.txt").write_text("a-LOCAL-unstaged\n")
    (canon / "b.txt").write_text("b-LOCAL-staged\n")
    g(canon, "add", "b.txt")
    (canon / "u.txt").write_text("untracked\n")


def detached_head(canon: Path) -> None:
    g(canon, "checkout", "-q", "--detach")


def _conflicting_branches(canon: Path) -> None:
    g(canon, "checkout", "-q", "-b", "other")
    commit(canon, {"b.txt": "b-other\n"}, "other")
    g(canon, "checkout", "-q", "-b", "work", "main")
    commit(canon, {"b.txt": "b-work\n"}, "work")


def rebasing_another_branch(canon: Path) -> None:
    _conflicting_branches(canon)
    assert g(canon, "rebase", "other", must=False).returncode != 0


def merging_on_another_branch(canon: Path) -> None:
    _conflicting_branches(canon)
    assert g(canon, "merge", "other", must=False).returncode != 0


def main_unstaged_no_overlap(canon: Path) -> None:
    (canon / "b.txt").write_text("b-LOCAL-unstaged\n")
    (canon / "u.txt").write_text("untracked\n")


def main_staged_no_overlap(canon: Path) -> None:
    (canon / "b.txt").write_text("b-LOCAL-staged\n")
    g(canon, "add", "b.txt")


def main_unstaged_overlap(canon: Path) -> None:
    (canon / "a.txt").write_text("a-LOCAL-unstaged\n")


def main_untracked_overlap(canon: Path) -> None:
    (canon / "c.txt").write_text("c-LOCAL-untracked\n")


class TestMainNotCheckedOut:
    """A fetch refspec advances main without touching HEAD, the index or the working tree."""

    @pytest.mark.parametrize("state", [
        other_branch_clean, other_branch_dirty, detached_head,
        rebasing_another_branch, merging_on_another_branch,
    ], ids=lambda f: f.__name__)
    def test_fetch_into_main_advances_it_and_leaves_work_alone(self, tmp_path, state):
        fx = build(tmp_path)
        state(fx.canon)
        before = snapshot(fx.canon)

        r = g(fx.canon, "fetch", "slot", "feat:main", must=False)

        after = snapshot(fx.canon)
        assert r.returncode == 0, r.stderr
        assert after.main == fx.feat
        assert after.head == before.head
        assert after.status == before.status
        assert after.files == before.files

    def test_non_fast_forward_is_rejected(self, tmp_path):
        fx = build(tmp_path)
        commit(fx.canon, {"b.txt": "b2\n"}, "canonical-only commit")
        g(fx.canon, "checkout", "-q", "-b", "work")
        before = snapshot(fx.canon)

        r = g(fx.canon, "fetch", "slot", "feat:main", must=False)

        assert r.returncode != 0
        assert "non-fast-forward" in r.stderr
        assert snapshot(fx.canon) == before


class TestMainCheckedOut:

    def test_fetch_into_checked_out_main_is_refused(self, tmp_path):
        fx = build(tmp_path)
        before = snapshot(fx.canon)

        r = g(fx.canon, "fetch", "slot", "feat:main", must=False)

        assert r.returncode != 0
        assert "refusing to fetch into branch" in r.stderr
        assert snapshot(fx.canon) == before

    def test_clean_main_fast_forwards(self, tmp_path):
        fx = build(tmp_path)

        r = attempt(fx.canon, FETCH_THEN_FF)

        after = snapshot(fx.canon)
        assert r.returncode == 0, r.stderr
        assert after.main == fx.feat
        assert after.status == ""
        assert after.files["a.txt"] == "a2\n" and after.files["c.txt"] == "c1\n"

    @pytest.mark.parametrize("state", [main_unstaged_no_overlap, main_staged_no_overlap],
                             ids=lambda f: f.__name__)
    def test_non_overlapping_local_changes_are_preserved(self, tmp_path, state):
        fx = build(tmp_path)
        state(fx.canon)
        before = snapshot(fx.canon)

        r = attempt(fx.canon, FETCH_THEN_FF)

        after = snapshot(fx.canon)
        assert r.returncode == 0, r.stderr
        assert after.main == fx.feat
        assert after.status == before.status
        assert after.files["b.txt"] == before.files["b.txt"]
        assert after.files["u.txt"] == before.files["u.txt"]

    @pytest.mark.parametrize("state,message", [
        (main_unstaged_overlap, "local changes to the following files would be overwritten"),
        (main_untracked_overlap, "untracked working tree files would be overwritten"),
    ], ids=["unstaged_overlap", "untracked_overlap"])
    def test_overlapping_local_changes_refuse_and_change_nothing(self, tmp_path, state, message):
        fx = build(tmp_path)
        state(fx.canon)
        before = snapshot(fx.canon)

        r = attempt(fx.canon, FETCH_THEN_FF)

        assert r.returncode != 0
        assert message in r.stderr
        assert snapshot(fx.canon) == before


class TestMainBusyElsewhere:

    def test_main_mid_rebase_refuses_fetch_into_it(self, tmp_path):
        def diverge(canon: Path) -> None:
            g(canon, "checkout", "-q", "-b", "other")
            commit(canon, {"b.txt": "b-other\n"}, "other")
            g(canon, "checkout", "-q", "main")
            commit(canon, {"b.txt": "b-main\n"}, "main-local")

        fx = build(tmp_path, pre_clone=diverge)
        assert g(fx.canon, "rebase", "other", must=False).returncode != 0
        before = snapshot(fx.canon)

        r = g(fx.canon, "fetch", "slot", "feat:main", must=False)

        assert r.returncode != 0
        assert "refusing to fetch into branch" in r.stderr
        assert snapshot(fx.canon) == before

    def test_main_in_linked_worktree_refuses_fetch_from_primary(self, tmp_path):
        fx = build(tmp_path)
        g(fx.canon, "checkout", "-q", "-b", "work")
        g(fx.canon, "worktree", "add", "-q", str(tmp_path / "wt"), "main")
        before = snapshot(fx.canon)

        r = g(fx.canon, "fetch", "slot", "feat:main", must=False)

        assert r.returncode != 0
        assert "refusing to fetch into branch" in r.stderr
        assert snapshot(fx.canon) == before

    def test_main_in_linked_worktree_fast_forwards_from_inside_it(self, tmp_path):
        fx = build(tmp_path)
        g(fx.canon, "checkout", "-q", "-b", "work")
        wt = tmp_path / "wt"
        g(fx.canon, "worktree", "add", "-q", str(wt), "main")

        r = attempt(wt, FETCH_THEN_FF)

        assert r.returncode == 0, r.stderr
        assert sha(fx.canon, "refs/heads/main") == fx.feat
        assert snapshot(fx.canon).head == "work"


class TestHoldingRef:

    @pytest.mark.parametrize("state", [other_branch_dirty, main_unstaged_overlap,
                                       rebasing_another_branch],
                             ids=lambda f: f.__name__)
    def test_fetch_into_holding_ref_works_in_any_state(self, tmp_path, state):
        fx = build(tmp_path)
        state(fx.canon)
        before = snapshot(fx.canon)

        r = g(fx.canon, "fetch", "slot", "feat:refs/landing/feat", must=False)

        assert r.returncode == 0, r.stderr
        assert sha(fx.canon, "refs/landing/feat") == fx.feat
        assert snapshot(fx.canon) == before


def with_remote(root: Path) -> tuple[Fixture, Path]:
    fx = build(root)
    remote = root / "remote.git"
    assert run("git", "init", "-q", "--bare", "-b", "main", str(remote)).returncode == 0
    g(fx.canon, "remote", "add", "origin", str(remote))
    g(fx.canon, "push", "-q", "origin", "main")
    return fx, remote


def someone_else_pushes(root: Path, remote: Path, name: str = "e.txt") -> str:
    other = root / f"other-{name}"
    assert run("git", "clone", "-q", str(remote), str(other)).returncode == 0
    commit(other, {name: "x\n"}, f"someone else adds {name}")
    g(other, "push", "-q", "origin", "main")
    return sha(remote, "refs/heads/main")


class TestCanonicalAndRemote:

    def test_push_main_while_on_another_dirty_branch(self, tmp_path):
        fx, remote = with_remote(tmp_path)
        other_branch_dirty(fx.canon)
        before = snapshot(fx.canon)
        g(fx.canon, "fetch", "slot", "feat:main")

        r = g(fx.canon, "push", "origin", "main", must=False)

        after = snapshot(fx.canon)
        assert r.returncode == 0, r.stderr
        assert sha(remote, "refs/heads/main") == fx.feat
        assert after.status == before.status and after.head == "work"

    def test_sync_main_from_remote_while_on_another_dirty_branch(self, tmp_path):
        fx, remote = with_remote(tmp_path)
        remote_tip = someone_else_pushes(tmp_path, remote)
        other_branch_dirty(fx.canon)
        before = snapshot(fx.canon)

        r = g(fx.canon, "fetch", "origin", "main:main", must=False)

        after = snapshot(fx.canon)
        assert r.returncode == 0, r.stderr
        assert after.main == remote_tip
        assert after.status == before.status and after.head == "work"

    def test_plain_push_is_rejected_when_remote_is_ahead(self, tmp_path):
        """Advancing canonical main before publishing can leave it diverged from the remote."""
        fx, remote = with_remote(tmp_path)
        remote_tip = someone_else_pushes(tmp_path, remote)
        g(fx.canon, "checkout", "-q", "-b", "work")
        g(fx.canon, "fetch", "slot", "feat:main")

        r = g(fx.canon, "push", "origin", "main", must=False)

        assert r.returncode != 0
        assert "rejected" in r.stderr
        assert sha(remote, "refs/heads/main") == remote_tip
        canon_main = sha(fx.canon, "refs/heads/main")
        g(fx.canon, "fetch", "-q", "origin")

        def is_ancestor(a: str, b: str) -> bool:
            return g(fx.canon, "merge-base", "--is-ancestor", a, b, must=False).returncode == 0

        assert not is_ancestor(canon_main, remote_tip), "canonical main holds a commit the remote lacks"
        assert not is_ancestor(remote_tip, canon_main), "canonical main lacks a commit the remote has"

    def test_publish_from_holding_ref_leaves_canonical_behind_not_diverged(self, tmp_path):
        fx, remote = with_remote(tmp_path)
        main_unstaged_overlap(fx.canon)
        before = snapshot(fx.canon)
        g(fx.canon, "fetch", "slot", "feat:refs/landing/feat")

        r = g(fx.canon, "push", "origin", "refs/landing/feat:refs/heads/main", must=False)

        after = snapshot(fx.canon)
        assert r.returncode == 0, r.stderr
        assert sha(remote, "refs/heads/main") == fx.feat
        assert after.main == before.main and after.status == before.status
        assert g(fx.canon, "merge-base", "--is-ancestor", after.main, fx.feat,
                 must=False).returncode == 0

    def test_rejected_publish_from_holding_ref_changes_nothing(self, tmp_path):
        fx, remote = with_remote(tmp_path)
        remote_tip = someone_else_pushes(tmp_path, remote)
        before = snapshot(fx.canon)
        g(fx.canon, "fetch", "slot", "feat:refs/landing/feat")

        r = g(fx.canon, "push", "origin", "refs/landing/feat:refs/heads/main", must=False)

        assert r.returncode != 0
        assert "rejected" in r.stderr
        assert sha(remote, "refs/heads/main") == remote_tip
        assert snapshot(fx.canon) == before
        assert sha(fx.canon, "refs/landing/feat") == fx.feat
