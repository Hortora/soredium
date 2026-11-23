"""The shared landing module (#515), on real repos.

Fixture: a blessed bare remote, a mirror bare remote, a canonical checkout whose
`upstream` is the blessed remote and `origin` the mirror, and a slot clone whose
only link to anything is a `local` remote pointing at canonical.

Global and system git config are disabled so user hooks cannot change an outcome.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

import canonical_sync as cs
from canonical_sync import SyncError


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "T")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "t@t")


def g(repo: Path, *args: str, must: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if must and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}:\n{result.stderr}")
    return result.stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    g(repo, "add", "-A")
    g(repo, "commit", "-q", "-m", message)
    return g(repo, "rev-parse", "HEAD")


def sha(repo: Path, ref: str) -> str:
    return g(repo, "rev-parse", "--verify", "-q", ref, must=False)


def merges(repo: Path, ref: str = "main") -> int:
    return int(g(repo, "rev-list", "--merges", "--count", ref))


@dataclass
class Family:
    root: Path
    blessed: Path
    mirror: Path
    canon: Path
    slot: Path

    def remote_main(self, remote: Path) -> str:
        return sha(remote, "refs/heads/main")

    def someone_else_pushes(self, files: dict[str, str], message: str = "other work") -> str:
        other = self.root / f"other-{len(list(self.root.iterdir()))}"
        subprocess.run(["git", "clone", "-q", str(self.blessed), str(other)],
                       capture_output=True, check=True)
        tip = commit(other, files, message)
        g(other, "push", "-q", "origin", "HEAD:main")
        return tip


def _bare(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(path)],
                   capture_output=True, check=True)
    return path


@pytest.fixture
def fam(tmp_path) -> Family:
    blessed = _bare(tmp_path / "blessed.git")
    mirror = _bare(tmp_path / "mirror.git")
    canon = tmp_path / "family" / "engine"
    canon.mkdir(parents=True)
    g(canon, "init", "-q", "-b", "main")
    commit(canon, {"a.txt": "a1\n", "b.txt": "b1\n"}, "init")
    g(canon, "remote", "add", "upstream", str(blessed))
    g(canon, "remote", "add", "origin", str(mirror))
    g(canon, "push", "-q", "upstream", "main")
    g(canon, "push", "-q", "origin", "main")
    g(canon, "fetch", "-q", "--all")
    slot_root = tmp_path / "family" / "slots" / "7"
    slot_root.mkdir(parents=True)
    (slot_root / ".slot").write_text("# Slot 7\n")
    slot = slot_root / "engine"
    subprocess.run(["git", "clone", "-q", "--shared", str(canon), str(slot)],
                   capture_output=True, check=True)
    g(slot, "remote", "rename", "origin", "local")
    g(slot, "checkout", "-q", "-b", "feat")
    commit(slot, {"a.txt": "a2\n", "c.txt": "c1\n"}, "feat: change a, add c")
    commit(slot, {"d.txt": "d1\n"}, "feat: add d")
    return Family(tmp_path, blessed, mirror, canon, slot)


def canon_state(canon: Path) -> tuple[str, str, str]:
    head = g(canon, "symbolic-ref", "-q", "--short", "HEAD", must=False) or "DETACHED"
    return sha(canon, "refs/heads/main"), head, g(canon, "status", "--porcelain")


def canon_moves(fam: "Family", files: dict[str, str]) -> str:
    """Canonical's base branch gains a commit on disk (as another landing would leave it)."""
    current = g(fam.canon, "symbolic-ref", "-q", "--short", "HEAD", must=False)
    if current != "main":
        g(fam.canon, "checkout", "-q", "main")
    tip = commit(fam.canon, files, "main moved on disk")
    if current and current != "main":
        g(fam.canon, "checkout", "-q", current)
    return tip


def on_dirty_work_branch(canon: Path) -> None:
    g(canon, "checkout", "-q", "-b", "work")
    (canon / "a.txt").write_text("uncommitted\n")
    (canon / "scratch.txt").write_text("untracked\n")


class TestLocate:
    def test_slot_clone_points_at_canonical(self, fam):
        found = cs.locate(fam.slot)
        assert found.repo == fam.canon.resolve()
        assert (found.base, found.blessed, found.mirror) == ("main", "upstream", "origin")

    def test_canonical_is_its_own_canonical(self, fam):
        assert cs.locate(fam.canon).repo.resolve() == fam.canon.resolve()

    def test_single_remote_is_blessed_with_no_mirror(self, fam):
        g(fam.canon, "remote", "remove", "upstream")
        found = cs.locate(fam.slot)
        assert (found.blessed, found.mirror) == ("origin", "")

    def test_repo_without_remotes(self, fam):
        g(fam.canon, "remote", "remove", "upstream")
        g(fam.canon, "remote", "remove", "origin")
        found = cs.locate(fam.canon)
        assert (found.blessed, found.mirror) == ("", "")

    def test_origin_with_a_fork_publishes_to_origin_and_mirrors_to_fork(self, fam):
        g(fam.canon, "remote", "rename", "upstream", "hub-main")
        g(fam.canon, "remote", "rename", "origin", "fork")
        g(fam.canon, "remote", "rename", "hub-main", "origin")
        g(fam.canon, "remote", "add", "slot207", str(fam.slot))
        found = cs.locate(fam.slot)
        assert (found.blessed, found.mirror) == ("origin", "fork")

    def test_slot_clone_without_a_local_remote_is_refused(self, fam):
        g(fam.slot, "remote", "remove", "local")
        with pytest.raises(SyncError) as raised:
            cs.locate(fam.slot)
        assert raised.value.code == "no_canonical"

    def test_local_remote_that_is_not_a_repo_is_refused(self, fam):
        g(fam.slot, "remote", "set-url", "local", str(fam.root))
        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")
        assert raised.value.code == "no_canonical"

    def test_command_line_reports_a_missing_canonical(self, fam, capsys):
        g(fam.slot, "remote", "remove", "local")
        assert cs.main(["status", str(fam.slot)]) == 1
        assert "ERROR=no_canonical" in capsys.readouterr().out

    def test_linked_worktree_of_canonical(self, fam):
        tree = fam.root / "linked"
        g(fam.canon, "worktree", "add", "-q", "-b", "side", str(tree))
        assert cs.locate(tree).repo.resolve() == fam.canon.resolve()


class TestLandFromSlot:
    def test_lands_in_canonical_and_pushes_nothing(self, fam):
        blessed_before = fam.remote_main(fam.blessed)
        mirror_before = fam.remote_main(fam.mirror)

        result = cs.land(fam.slot, "feat")

        tip = sha(fam.slot, "feat")
        assert result.sha == tip == sha(fam.canon, "refs/heads/main")
        assert result.unpublished == 2
        assert result.warnings == []
        assert fam.remote_main(fam.blessed) == blessed_before
        assert fam.remote_main(fam.mirror) == mirror_before
        assert merges(fam.canon) == 0

    def test_every_commit_of_the_branch_is_kept(self, fam):
        cs.land(fam.slot, "feat")
        subjects = g(fam.canon, "log", "--format=%s", "main").splitlines()
        assert subjects == ["feat: add d", "feat: change a, add c", "init"]

    def test_holding_ref_is_removed_and_slot_main_follows(self, fam):
        cs.land(fam.slot, "feat")
        assert sha(fam.canon, "refs/landing/feat") == ""
        assert sha(fam.slot, "refs/heads/main") == sha(fam.canon, "refs/heads/main")

    def test_slot_gains_no_remote(self, fam):
        cs.land(fam.slot, "feat")
        assert g(fam.slot, "remote").split() == ["local"]

    def test_canonical_on_a_dirty_branch_is_left_alone(self, fam):
        on_dirty_work_branch(fam.canon)
        _, head, status = canon_state(fam.canon)

        cs.land(fam.slot, "feat")

        assert canon_state(fam.canon) == (sha(fam.slot, "feat"), head, status)
        assert (fam.canon / "a.txt").read_text() == "uncommitted\n"

    def test_canonical_on_clean_main_moves_its_working_tree(self, fam):
        cs.land(fam.slot, "feat")
        assert (fam.canon / "d.txt").read_text() == "d1\n"
        assert g(fam.canon, "status", "--porcelain") == ""

    def test_canonical_on_main_with_unrelated_edit_keeps_the_edit(self, fam):
        (fam.canon / "b.txt").write_text("local edit\n")

        cs.land(fam.slot, "feat")

        assert sha(fam.canon, "refs/heads/main") == sha(fam.slot, "feat")
        assert (fam.canon / "b.txt").read_text() == "local edit\n"

    def test_overlapping_edit_on_main_refuses_and_changes_nothing(self, fam):
        before = sha(fam.canon, "refs/heads/main")
        (fam.canon / "a.txt").write_text("local edit\n")

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")

        assert raised.value.code == "advance_blocked"
        assert sha(fam.canon, "refs/heads/main") == before
        assert (fam.canon / "a.txt").read_text() == "local edit\n"

    def test_landing_succeeds_once_the_overlapping_edit_is_gone(self, fam):
        (fam.canon / "a.txt").write_text("local edit\n")
        with pytest.raises(SyncError):
            cs.land(fam.slot, "feat")
        g(fam.canon, "checkout", "--", "a.txt")

        result = cs.land(fam.slot, "feat")

        assert result.sha == sha(fam.slot, "feat") == sha(fam.canon, "refs/heads/main")

    def test_landing_twice_is_a_no_op(self, fam):
        cs.land(fam.slot, "feat")
        again = cs.land(fam.slot, "feat")
        assert again.already_landed is True
        assert again.unpublished == 2
        assert merges(fam.canon) == 0

    def test_before_sha_records_canonical_main_before_landing(self, fam):
        main_before = sha(fam.canon, "refs/heads/main")
        result = cs.land(fam.slot, "feat")
        assert result.before_sha == main_before
        assert result.sha != main_before, "landing must move canonical main"

    def test_already_landed_has_before_sha_equal_to_sha(self, fam):
        cs.land(fam.slot, "feat")
        again = cs.land(fam.slot, "feat")
        assert again.already_landed is True
        assert again.before_sha == again.sha

    def test_landing_with_commits_always_moves_canonical_main(self, fam):
        main_before = sha(fam.canon, "refs/heads/main")
        result = cs.land(fam.slot, "feat")
        main_after = sha(fam.canon, "refs/heads/main")
        assert main_after != main_before
        assert result.sha == main_after


class TestLandingIgnoresTheRemote:
    """Landing is an on-disk operation. Bringing canonical up to a remote is publishing's job."""

    def test_remote_ahead_is_not_fetched(self, fam):
        theirs = fam.someone_else_pushes({"e.txt": "e1\n"})
        remote_ref = sha(fam.canon, "refs/remotes/upstream/main")

        result = cs.land(fam.slot, "feat")

        assert result.sha == sha(fam.slot, "feat") == sha(fam.canon, "refs/heads/main")
        assert not (fam.canon / "e.txt").exists()
        assert sha(fam.canon, "refs/remotes/upstream/main") == remote_ref
        assert fam.remote_main(fam.blessed) == theirs

    def test_unreachable_remote_makes_no_difference(self, fam):
        g(fam.canon, "remote", "set-url", "upstream", str(fam.root / "gone.git"))
        g(fam.canon, "remote", "set-url", "origin", str(fam.root / "gone-too.git"))

        result = cs.land(fam.slot, "feat")

        assert result.sha == sha(fam.slot, "feat") == sha(fam.canon, "refs/heads/main")
        assert result.warnings == []

    def test_canonical_ahead_of_remote_lands_on_top_of_its_own_commits(self, fam):
        local_only = commit(fam.canon, {"local.txt": "unpublished\n"}, "local only")

        result = cs.land(fam.slot, "feat")

        g(fam.canon, "merge-base", "--is-ancestor", local_only, "main")
        assert result.unpublished == 3
        assert merges(fam.canon) == 0

    def test_canonical_base_moved_on_disk_is_rebased_onto(self, fam):
        g(fam.canon, "checkout", "-q", "-b", "work")
        other = fam.root / "family" / "slots" / "7" / "second"
        subprocess.run(["git", "clone", "-q", "--shared", str(fam.canon), str(other)],
                       capture_output=True, check=True)
        g(other, "remote", "rename", "origin", "local")
        g(other, "checkout", "-q", "-b", "first", "local/main")
        first = commit(other, {"e.txt": "e1\n"}, "feat: e")
        cs.land(other, "first")

        result = cs.land(fam.slot, "feat")

        g(fam.canon, "merge-base", "--is-ancestor", first, "main")
        assert g(fam.canon, "rev-list", "--count", f"{first}..main") == "2"
        assert result.sha == sha(fam.slot, "feat")
        assert merges(fam.canon) == 0

    def test_slot_tracking_refs_follow_canonical_after_landing(self, fam):
        cs.land(fam.slot, "feat")
        assert sha(fam.slot, "refs/remotes/local/main") == sha(fam.canon, "refs/heads/main")
        assert g(fam.slot, "rev-list", "--count", "local/main..feat") == "0"


class TestRebase:
    def test_conflict_aborts_its_own_rebase_and_changes_nothing(self, fam):
        canon_moves(fam, {"a.txt": "theirs\n"})
        canon_before = sha(fam.canon, "refs/heads/main")
        branch_before = sha(fam.slot, "feat")

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")

        assert raised.value.code == "rebase_conflict"
        assert "a.txt" in raised.value.detail
        assert sha(fam.slot, "feat") == branch_before
        assert g(fam.slot, "status", "--porcelain") == ""
        assert g(fam.slot, "symbolic-ref", "--short", "HEAD") == "feat"
        assert not (fam.slot / ".git" / "rebase-merge").exists()
        assert sha(fam.canon, "refs/heads/main") == canon_before

    def test_rebase_already_in_progress_is_never_aborted(self, fam):
        g(fam.slot, "checkout", "-q", "-b", "clash", "main")
        commit(fam.slot, {"a.txt": "clash\n"}, "clash")
        g(fam.slot, "checkout", "-q", "feat")
        g(fam.slot, "rebase", "clash", must=False)
        assert (fam.slot / ".git" / "rebase-merge").exists()
        canon_moves(fam, {"e.txt": "e1\n"})

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")

        assert raised.value.code == "busy"
        assert (fam.slot / ".git" / "rebase-merge").exists()

    def test_branch_not_checked_out_is_rebased_without_switching_anything(self, fam):
        g(fam.slot, "checkout", "-q", "-b", "elsewhere", "main")
        (fam.slot / "b.txt").write_text("uncommitted in slot\n")
        canon_moves(fam, {"e.txt": "e1\n"})

        result = cs.land(fam.slot, "feat")

        assert g(fam.slot, "symbolic-ref", "--short", "HEAD") == "elsewhere"
        assert (fam.slot / "b.txt").read_text() == "uncommitted in slot\n"
        assert sha(fam.canon, "refs/heads/main") == result.sha == sha(fam.slot, "feat")
        assert len(g(fam.slot, "worktree", "list").splitlines()) == 1

    def test_dirty_checkout_of_the_branch_refuses_and_changes_nothing(self, fam):
        canon_moves(fam, {"e.txt": "e1\n"})
        (fam.slot / "a.txt").write_text("uncommitted\n")
        before = sha(fam.slot, "feat")

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")

        assert raised.value.code == "rebase_refused"
        assert sha(fam.slot, "feat") == before
        assert (fam.slot / "a.txt").read_text() == "uncommitted\n"

    def test_refresh_brings_a_branch_up_to_the_published_base(self, fam):
        theirs = fam.someone_else_pushes({"e.txt": "e1\n"})

        cs.refresh(fam.slot, "feat")

        g(fam.slot, "merge-base", "--is-ancestor", theirs, "feat")
        assert sha(fam.canon, "refs/heads/main") == theirs      # the branch itself did not land


class TestWorkInCanonicalItself:
    """Today's non-slot layout: the branch lives in the canonical checkout."""

    def _branch_in_canon(self, fam) -> str:
        g(fam.canon, "checkout", "-q", "-b", "fix")
        return commit(fam.canon, {"f.txt": "f1\n"}, "fix: f")

    def test_branch_checked_out_in_canonical(self, fam):
        tip = self._branch_in_canon(fam)

        result = cs.land(fam.canon, "fix")

        assert result.sha == tip == sha(fam.canon, "refs/heads/main")
        assert g(fam.canon, "symbolic-ref", "--short", "HEAD") == "fix"

    def test_branch_in_a_linked_worktree_is_rebased_there(self, fam):
        tree = fam.root / "linked"
        g(fam.canon, "worktree", "add", "-q", "-b", "fix", str(tree))
        commit(tree, {"f.txt": "f1\n"}, "fix: f")
        canon_moves(fam, {"e.txt": "e1\n"})
        on_dirty_work_branch(fam.canon)
        _, head, status = canon_state(fam.canon)

        result = cs.land(tree, "fix")

        assert (tree / "e.txt").exists()
        assert g(tree, "symbolic-ref", "--short", "HEAD") == "fix"
        assert canon_state(fam.canon) == (result.sha, head, status)
        assert result.sha == sha(tree, "fix")

    def test_branch_checked_out_nowhere_while_canonical_is_dirty_elsewhere(self, fam):
        self._branch_in_canon(fam)
        g(fam.canon, "checkout", "-q", "main")
        canon_moves(fam, {"e.txt": "e1\n"})
        on_dirty_work_branch(fam.canon)
        _, head, status = canon_state(fam.canon)

        result = cs.land(fam.canon, "fix")

        assert canon_state(fam.canon) == (result.sha, head, status)
        assert result.sha == sha(fam.canon, "fix")
        assert len(g(fam.canon, "worktree", "list").splitlines()) == 1

    def test_main_in_a_linked_worktree_fast_forwards_there(self, fam):
        g(fam.canon, "checkout", "-q", "-b", "work")
        tree = fam.root / "main-tree"
        g(fam.canon, "worktree", "add", "-q", str(tree), "main")

        cs.land(fam.slot, "feat")

        assert (tree / "d.txt").exists()
        assert g(tree, "status", "--porcelain") == ""


class TestBaseBusy:
    def test_main_mid_rebase_stops_and_is_never_aborted(self, fam):
        g(fam.canon, "checkout", "-q", "-b", "clash")
        commit(fam.canon, {"a.txt": "clash\n"}, "clash")
        g(fam.canon, "checkout", "-q", "main")
        commit(fam.canon, {"a.txt": "main side\n"}, "main side")
        g(fam.canon, "rebase", "clash", must=False)
        assert (fam.canon / ".git" / "rebase-merge").exists()
        main_before = sha(fam.canon, "refs/heads/main")

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")

        assert raised.value.code == "base_busy"
        assert (fam.canon / ".git" / "rebase-merge").exists()
        assert sha(fam.canon, "refs/heads/main") == main_before


class TestNoRemote:
    def test_repo_without_a_remote_lands_in_canonical(self, fam):
        g(fam.canon, "remote", "remove", "upstream")
        g(fam.canon, "remote", "remove", "origin")

        result = cs.land(fam.slot, "feat")

        assert result.unpublished == 0
        assert sha(fam.canon, "refs/heads/main") == sha(fam.slot, "feat")

    def test_publishing_it_reports_there_is_nowhere_to_publish(self, fam):
        g(fam.canon, "remote", "remove", "upstream")
        g(fam.canon, "remote", "remove", "origin")
        cs.land(fam.slot, "feat")

        result = cs.publish_base(fam.canon)

        assert result.published == "none"
        assert "no remote" in result.warnings[0]


class TestPublish:
    def test_publishes_everything_landed_since_the_last_publish(self, fam):
        cs.land(fam.slot, "feat")

        result = cs.publish_base(fam.canon)

        tip = sha(fam.canon, "refs/heads/main")
        assert (result.published, result.mirrored, result.pushed) == ("upstream", "origin", 2)
        assert result.sha == tip == fam.remote_main(fam.blessed) == fam.remote_main(fam.mirror)
        assert cs.unpublished(cs.locate(fam.canon)) == 0

    def test_can_be_asked_from_the_slot_but_canonical_does_the_push(self, fam):
        cs.land(fam.slot, "feat")

        result = cs.publish_base(fam.slot)

        assert result.repo == fam.canon.resolve()
        assert fam.remote_main(fam.blessed) == sha(fam.canon, "refs/heads/main")
        assert g(fam.slot, "remote").split() == ["local"]

    def test_nothing_to_publish_is_a_no_op(self, fam):
        before = fam.remote_main(fam.blessed)
        result = cs.publish_base(fam.canon)
        assert result.pushed == 0
        assert fam.remote_main(fam.blessed) == before

    def test_works_while_canonical_is_on_a_dirty_branch(self, fam):
        cs.land(fam.slot, "feat")
        on_dirty_work_branch(fam.canon)
        before = canon_state(fam.canon)

        cs.publish_base(fam.canon)

        assert canon_state(fam.canon) == before
        assert fam.remote_main(fam.blessed) == before[0]

    def test_fork_gets_the_work_first_as_a_branch(self, fam, monkeypatch):
        cs.land(fam.slot, "feat")
        tip = sha(fam.canon, "refs/heads/main")
        mirror_main = fam.remote_main(fam.mirror)

        def blessed_refuses(canon):
            raise SyncError("publish_failed", "blessed is down")

        monkeypatch.setattr(cs, "_push_base", blessed_refuses)
        with pytest.raises(SyncError):
            cs.publish_base(fam.canon)

        assert sha(fam.mirror, "refs/heads/publish/main") == tip     # off the machine already
        assert fam.remote_main(fam.mirror) == mirror_main             # fork main only follows
        assert fam.remote_main(fam.blessed) != tip

    def test_publish_reports_where_it_staged(self, fam):
        cs.land(fam.slot, "feat")
        result = cs.publish_base(fam.canon)
        assert result.staged == "origin/publish/main"
        assert sha(fam.mirror, "refs/heads/publish/main") == result.sha
        assert result.rebased == 0

    def test_remote_moved_since_landing_rebases_only_the_unpublished_commits(self, fam):
        cs.land(fam.slot, "feat")
        theirs = fam.someone_else_pushes({"e.txt": "e1\n"})

        result = cs.publish_base(fam.canon)

        assert result.rebased == 2 and result.pushed == 2
        g(fam.blessed, "merge-base", "--is-ancestor", theirs, "main")
        assert g(fam.blessed, "log", "--format=%s", "-3", "main").splitlines() == [
            "feat: add d", "feat: change a, add c", "other work"]
        tip = sha(fam.canon, "refs/heads/main")
        assert tip == fam.remote_main(fam.blessed) == fam.remote_main(fam.mirror)
        assert sha(fam.mirror, "refs/heads/publish/main") == tip
        assert merges(fam.canon) == 0
        assert (fam.canon / "e.txt").read_text() == "e1\n"
        assert g(fam.canon, "status", "--porcelain") == ""

    def test_rebase_at_publish_leaves_a_canonical_checkout_on_another_branch_alone(self, fam):
        cs.land(fam.slot, "feat")
        fam.someone_else_pushes({"e.txt": "e1\n"})
        on_dirty_work_branch(fam.canon)
        _, head, status = canon_state(fam.canon)

        result = cs.publish_base(fam.canon)

        assert result.rebased == 2
        assert canon_state(fam.canon) == (fam.remote_main(fam.blessed), head, status)
        assert len(g(fam.canon, "worktree", "list").splitlines()) == 1

    def test_conflict_with_the_moved_remote_refuses_and_changes_nothing(self, fam):
        cs.land(fam.slot, "feat")
        theirs = fam.someone_else_pushes({"a.txt": "theirs\n"})
        main_before = sha(fam.canon, "refs/heads/main")

        with pytest.raises(SyncError) as raised:
            cs.publish_base(fam.canon)

        assert raised.value.code == "rebase_conflict"
        assert "a.txt" in raised.value.detail
        assert sha(fam.canon, "refs/heads/main") == main_before
        assert fam.remote_main(fam.blessed) == theirs
        assert g(fam.canon, "status", "--porcelain") == ""
        assert not (fam.canon / ".git" / "rebase-merge").exists()

    def test_uncommitted_changes_on_the_base_checkout_refuse_the_rebase(self, fam):
        cs.land(fam.slot, "feat")
        theirs = fam.someone_else_pushes({"e.txt": "e1\n"})
        (fam.canon / "b.txt").write_text("uncommitted\n")
        main_before = sha(fam.canon, "refs/heads/main")

        with pytest.raises(SyncError) as raised:
            cs.publish_base(fam.canon)

        assert raised.value.code == "rebase_refused"
        assert sha(fam.canon, "refs/heads/main") == main_before
        assert (fam.canon / "b.txt").read_text() == "uncommitted\n"
        assert fam.remote_main(fam.blessed) == theirs

    def test_commits_already_upstream_under_new_shas_drop_out(self, fam):
        """What a rebase-merged pull request leaves: the same changes, different SHAs."""
        cs.land(fam.slot, "feat")
        other = fam.root / "merger"
        subprocess.run(["git", "clone", "-q", str(fam.blessed), str(other)],
                       capture_output=True, check=True)
        g(other, "fetch", "-q", str(fam.canon), "main")
        g(other, "-c", "user.name=Merger", "-c", "user.email=m@m",
          "cherry-pick", "HEAD..FETCH_HEAD")
        g(other, "push", "-q", "origin", "HEAD:main")
        upstream = fam.remote_main(fam.blessed)
        assert upstream != sha(fam.canon, "refs/heads/main")

        result = cs.publish_base(fam.canon)

        assert sha(fam.canon, "refs/heads/main") == upstream == fam.remote_main(fam.blessed)
        assert result.pushed == 0
        assert merges(fam.canon) == 0

    def test_remote_ahead_with_nothing_local_just_catches_canonical_up(self, fam):
        theirs = fam.someone_else_pushes({"e.txt": "e1\n"})

        result = cs.publish_base(fam.canon)

        assert result.pushed == 0
        assert sha(fam.canon, "refs/heads/main") == theirs == fam.remote_main(fam.blessed)

    def test_mirror_failure_warns_and_the_publish_stands(self, fam):
        cs.land(fam.slot, "feat")
        g(fam.canon, "remote", "set-url", "origin", str(fam.root / "gone.git"))

        result = cs.publish_base(fam.canon)

        assert (result.published, result.staged, result.mirrored) == ("upstream", "failed", "failed")
        assert len(result.warnings) == 2
        assert fam.remote_main(fam.blessed) == sha(fam.canon, "refs/heads/main")

    def test_mirror_diagnoses_divergence(self, fam):
        """When the fork has commits canonical doesn't, mirror returns 'diverged'."""
        cs.land(fam.slot, "feat")
        ci_clone = fam.root / "ci-sim"
        subprocess.run(["git", "clone", "-q", str(fam.mirror), str(ci_clone)],
                       capture_output=True, check=True)
        commit(ci_clone, {"ci-docs.txt": "generated\n"},
               "docs: regenerate API docs [skip ci]")
        g(ci_clone, "push", "-q", "origin", "main")

        result = cs.publish_base(fam.canon)

        assert result.mirrored == "diverged"
        assert result.published == "upstream"
        assert any("diverged" in w for w in result.warnings)
        assert any("regenerate" in w for w in result.warnings)
        assert not any("catches up" in w for w in result.warnings)

    def test_mirror_reports_network_failure_not_diverged(self, fam):
        """When the fork is unreachable, mirror returns 'failed', not 'diverged'."""
        cs.land(fam.slot, "feat")
        g(fam.canon, "remote", "set-url", "origin", str(fam.root / "gone.git"))

        result = cs.publish_base(fam.canon)

        assert result.mirrored == "failed"
        assert result.published == "upstream"
        assert not any("diverged" in w for w in result.warnings)

    def test_mirror_succeeds_when_canonical_ahead(self, fam):
        """Normal case: canonical has work the fork doesn't, push is ff."""
        cs.land(fam.slot, "feat")

        result = cs.publish_base(fam.canon)

        assert result.mirrored == "origin"
        assert result.published == "upstream"
        assert not result.warnings

    def test_blessed_unreachable_is_an_error_and_nothing_changes(self, fam):
        cs.land(fam.slot, "feat")
        g(fam.canon, "remote", "set-url", "upstream", str(fam.root / "gone.git"))
        before = canon_state(fam.canon)

        with pytest.raises(SyncError) as raised:
            cs.publish_base(fam.canon)

        assert raised.value.code == "fetch_failed"
        assert canon_state(fam.canon) == before

    def test_empty_blessed_remote_receives_the_first_push(self, fam):
        empty = _bare(fam.root / "empty.git")
        g(fam.canon, "remote", "set-url", "upstream", str(empty))
        cs.land(fam.slot, "feat")

        result = cs.publish_base(fam.canon)

        assert sha(empty, "refs/heads/main") == result.sha

    def test_command_line_reports_status_then_publishes(self, fam, capsys):
        cs.land(fam.slot, "feat")

        assert cs.main(["status", str(fam.slot)]) == 0
        assert "UNPUBLISHED=2" in capsys.readouterr().out
        assert fam.remote_main(fam.blessed) != sha(fam.canon, "refs/heads/main")

        assert cs.main(["publish", str(fam.slot)]) == 0
        out = capsys.readouterr().out
        assert "PUBLISHED=upstream" in out and "PUSHED=2" in out and "MIRRORED=origin" in out
        assert "STAGED=origin/publish/main" in out and "REBASED=0" in out
        assert fam.remote_main(fam.blessed) == sha(fam.canon, "refs/heads/main")

    def test_command_line_reports_a_conflict_as_an_error(self, fam, capsys):
        cs.land(fam.slot, "feat")
        fam.someone_else_pushes({"a.txt": "theirs\n"})

        assert cs.main(["publish", str(fam.canon)]) == 1
        assert "ERROR=rebase_conflict" in capsys.readouterr().out


class TestLandAll:
    def _second_repo(self, fam) -> tuple[Path, Path]:
        canon = fam.root / "family" / "agency"
        canon.mkdir()
        g(canon, "init", "-q", "-b", "main")
        commit(canon, {"x.txt": "x1\n"}, "init")
        slot = fam.root / "family" / "slots" / "7" / "agency"
        subprocess.run(["git", "clone", "-q", "--shared", str(canon), str(slot)],
                       capture_output=True, check=True)
        g(slot, "remote", "rename", "origin", "local")
        g(slot, "checkout", "-q", "-b", "feat")
        commit(slot, {"x.txt": "x2\n"}, "feat: x")
        return canon, slot

    def test_lands_every_repo_and_reports_in_request_order(self, fam):
        canon2, slot2 = self._second_repo(fam)

        results = cs.land_all([(slot2, "feat"), (fam.slot, "feat")])

        assert [r.repo for r in results] == [slot2, fam.slot]
        assert sha(canon2, "refs/heads/main") == sha(slot2, "feat")
        assert sha(fam.canon, "refs/heads/main") == sha(fam.slot, "feat")

    def test_before_sha_is_captured_per_canonical(self, fam):
        canon2, slot2 = self._second_repo(fam)
        before1 = sha(fam.canon, "refs/heads/main")
        before2 = sha(canon2, "refs/heads/main")

        results = cs.land_all([(fam.slot, "feat"), (slot2, "feat")])

        assert results[0].before_sha == before1
        assert results[1].before_sha == before2
        assert results[0].sha != before1
        assert results[1].sha != before2

    def test_a_conflict_in_one_repo_lands_none(self, fam):
        canon2, slot2 = self._second_repo(fam)
        commit(canon2, {"x.txt": "canonical moved\n"}, "main moved")
        canon_before = sha(fam.canon, "refs/heads/main")
        canon2_before = sha(canon2, "refs/heads/main")

        with pytest.raises(SyncError) as raised:
            cs.land_all([(fam.slot, "feat"), (slot2, "feat")])

        assert raised.value.code == "rebase_conflict"
        assert sha(fam.canon, "refs/heads/main") == canon_before
        assert sha(canon2, "refs/heads/main") == canon2_before


class TestLock:
    def test_second_landing_waits_then_gives_up(self, fam):
        canon = cs.locate(fam.slot)
        before = sha(fam.canon, "refs/heads/main")
        with cs.landing_lock(canon):
            holder = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, sys.argv[1]); import canonical_sync as cs\n"
                 "try:\n"
                 "    cs.land(sys.argv[2], 'feat', lock_timeout=0.5)\n"
                 "except cs.SyncError as e:\n"
                 "    print(e.code)\n",
                 str(Path(cs.__file__).parent), str(fam.slot)],
                capture_output=True, text=True)
        assert holder.stdout.strip() == "locked"
        assert sha(fam.canon, "refs/heads/main") == before

    def test_lock_is_released_after_a_failed_landing(self, fam):
        canon_moves(fam, {"a.txt": "theirs\n"})
        with pytest.raises(SyncError):
            cs.land(fam.slot, "feat")
        with cs.landing_lock(cs.locate(fam.slot), timeout=0.5):
            pass

    def test_publish_and_landing_share_the_lock(self, fam):
        with cs.landing_lock(cs.locate(fam.slot)):
            with pytest.raises(SyncError) as raised:
                cs.publish_base(fam.canon, lock_timeout=0.3)
        assert raised.value.code == "locked"


class TestBackup:
    def test_slot_branch_is_kept_in_canonical_under_the_slot_name(self, fam):
        ref = cs.backup(fam.slot, "feat")
        assert ref == "refs/backup/7/feat"
        assert sha(fam.canon, ref) == sha(fam.slot, "feat")

    def test_works_while_canonical_is_dirty_and_touches_nothing(self, fam):
        on_dirty_work_branch(fam.canon)
        before = canon_state(fam.canon)
        cs.backup(fam.slot, "feat")
        assert canon_state(fam.canon) == before

    def test_follows_a_rewritten_branch(self, fam):
        cs.backup(fam.slot, "feat")
        g(fam.slot, "commit", "-q", "--amend", "-m", "feat: add d, reworded")
        ref = cs.backup(fam.slot, "feat")
        assert sha(fam.canon, ref) == sha(fam.slot, "feat")

    def test_nothing_is_pushed_to_any_remote(self, fam):
        cs.backup(fam.slot, "feat")
        assert g(fam.blessed, "for-each-ref", "--format=%(refname)") == "refs/heads/main"
        assert g(fam.mirror, "for-each-ref", "--format=%(refname)") == "refs/heads/main"


class TestBackupCommand:
    """What the slot post-commit hook runs: `canonical_sync.py backup <repo> offsite=yes`."""

    def _marker(self, fam) -> Path:
        return fam.slot / ".git" / "soredium-backup-failed"

    def test_backs_up_the_checked_out_branch_into_canonical(self, fam, capsys):
        assert cs.main(["backup", str(fam.slot)]) == 0
        out = capsys.readouterr().out
        assert "BACKUP_REF=refs/backup/7/feat" in out
        assert sha(fam.canon, "refs/backup/7/feat") == sha(fam.slot, "feat")

    def test_offsite_goes_to_the_fork_as_a_ref_that_is_not_a_branch(self, fam, capsys):
        assert cs.main(["backup", str(fam.slot), "offsite=yes"]) == 0
        out = capsys.readouterr().out
        assert "BACKUP_OFFSITE=origin" in out
        assert sha(fam.mirror, "refs/backup/7/feat") == sha(fam.slot, "feat")
        assert g(fam.mirror, "for-each-ref", "--format=%(refname)", "refs/heads") == "refs/heads/main"
        assert g(fam.blessed, "for-each-ref", "--format=%(refname)") == "refs/heads/main"

    def test_offsite_failure_is_reported_and_remembered_not_swallowed(self, fam, capsys):
        g(fam.canon, "remote", "set-url", "origin", str(fam.root / "gone.git"))

        assert cs.main(["backup", str(fam.slot), "offsite=yes"]) == 1

        captured = capsys.readouterr()
        assert "BACKUP_OFFSITE=failed" in captured.out
        assert "backup" in captured.err.lower() and "origin" in captured.err
        assert sha(fam.canon, "refs/backup/7/feat") == sha(fam.slot, "feat")   # on disk regardless
        assert self._marker(fam).exists()
        assert cs.main(["status", str(fam.slot)]) == 0
        assert "BACKUP_FAILED=" in capsys.readouterr().out

    def test_next_success_clears_the_failure(self, fam, capsys):
        good = g(fam.canon, "remote", "get-url", "origin")
        g(fam.canon, "remote", "set-url", "origin", str(fam.root / "gone.git"))
        cs.main(["backup", str(fam.slot), "offsite=yes"])
        g(fam.canon, "remote", "set-url", "origin", good)

        assert cs.main(["backup", str(fam.slot), "offsite=yes"]) == 0

        assert not self._marker(fam).exists()
        capsys.readouterr()
        cs.main(["status", str(fam.slot)])
        assert "BACKUP_FAILED=" not in capsys.readouterr().out

    def test_single_remote_gets_no_offsite_copy_unless_configured(self, fam, capsys):
        g(fam.canon, "remote", "remove", "origin")           # only the blessed remote is left
        g(fam.canon, "remote", "rename", "upstream", "origin")

        assert cs.main(["backup", str(fam.slot), "offsite=yes"]) == 0
        assert "BACKUP_OFFSITE=none" in capsys.readouterr().out
        assert sha(fam.blessed, "refs/backup/7/feat") == ""

        g(fam.canon, "config", "soredium.backupRemote", "origin")
        assert cs.main(["backup", str(fam.slot), "offsite=yes"]) == 0
        assert "BACKUP_OFFSITE=origin" in capsys.readouterr().out
        assert sha(fam.blessed, "refs/backup/7/feat") == sha(fam.slot, "feat")

    def test_detached_head_is_not_an_error(self, fam, capsys):
        g(fam.slot, "checkout", "-q", "--detach")
        assert cs.main(["backup", str(fam.slot), "offsite=yes"]) == 0
        assert "BACKUP_REF=none" in capsys.readouterr().out

    def test_slot_with_no_canonical_fails_loudly(self, fam, capsys):
        g(fam.slot, "remote", "remove", "local")
        assert cs.main(["backup", str(fam.slot)]) == 1
        captured = capsys.readouterr()
        assert "ERROR=no_canonical" in captured.out
        assert self._marker(fam).exists()


class TestPostCommitHook:
    """The hook as git runs it, end to end."""

    def _install(self, fam, monkeypatch):
        sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
        import slot_git
        monkeypatch.setenv("SOREDIUM_CANONICAL_SYNC", str(Path(cs.__file__)))
        slot_git.install_post_commit_hook(fam.slot)

    def test_a_commit_in_the_slot_is_copied_to_canonical_and_the_fork(self, fam, monkeypatch):
        self._install(fam, monkeypatch)

        tip = commit(fam.slot, {"new.txt": "n\n"}, "feat: new")

        assert sha(fam.canon, "refs/backup/7/feat") == tip
        assert sha(fam.mirror, "refs/backup/7/feat") == tip
        assert g(fam.mirror, "for-each-ref", "--format=%(refname)", "refs/heads") == "refs/heads/main"

    def test_a_failed_backup_is_visible_to_the_committer(self, fam, monkeypatch):
        self._install(fam, monkeypatch)
        g(fam.canon, "remote", "set-url", "origin", str(fam.root / "gone.git"))
        (fam.slot / "new.txt").write_text("n\n")
        g(fam.slot, "add", "-A")

        result = subprocess.run(["git", "-C", str(fam.slot), "commit", "-m", "feat: new"],
                                capture_output=True, text=True)

        assert result.returncode == 0                      # the commit itself stands
        assert "backup" in result.stderr.lower()
        assert (fam.slot / ".git" / "soredium-backup-failed").exists()


RETIRED_HOOK = """#!/bin/bash
echo "Run /git-squash to review history before pushing, or use --no-verify to skip."
exit 1
"""
REFUSING_HOOK = "#!/bin/sh\necho 'policy: not today' >&2\nexit 1\n"
LINEAR_HOOK = (Path(__file__).resolve().parent.parent / "git-squash" / "hooks" / "pre-push")


def _hook(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    hook = directory / "pre-push"
    hook.write_text(text)
    hook.chmod(0o755)
    return hook


class TestPushHook:
    """#551: publish names the hook that stands in its way and never hides its output."""

    def test_no_hook(self, fam):
        assert cs.push_hook(fam.canon) is None
        assert cs.retired_push_hook(fam.canon) is None

    def test_hook_in_git_hooks_is_found(self, fam):
        hook = _hook(fam.canon / ".git" / "hooks", REFUSING_HOOK)
        assert cs.push_hook(fam.canon).resolve() == hook.resolve()

    def test_local_hooks_path_wins_over_git_hooks(self, fam):
        _hook(fam.canon / ".git" / "hooks", REFUSING_HOOK)
        tracked = _hook(fam.canon / ".githooks", RETIRED_HOOK)
        g(fam.canon, "config", "core.hooksPath", ".githooks")
        assert cs.push_hook(fam.canon).resolve() == tracked.resolve()
        assert cs.retired_push_hook(fam.canon).resolve() == tracked.resolve()

    def test_global_hooks_path_is_followed(self, fam, tmp_path, monkeypatch):
        shared = _hook(tmp_path / "shared-hooks", REFUSING_HOOK)
        config = tmp_path / "global.gitconfig"
        config.write_text(f"[core]\n\thooksPath = {shared.parent}\n"
                          "[user]\n\tname = T\n\temail = t@t\n")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
        _hook(fam.canon / ".git" / "hooks", RETIRED_HOOK)
        assert cs.push_hook(fam.canon).resolve() == shared.resolve()
        assert cs.retired_push_hook(fam.canon) is None

    def test_the_linear_hook_is_not_retired(self, fam):
        _hook(fam.canon / ".git" / "hooks", LINEAR_HOOK.read_text())
        assert cs.retired_push_hook(fam.canon) is None

    def test_publish_refuses_before_pushing_when_the_hook_is_retired(self, fam):
        cs.land(fam.slot, "feat")
        hook = _hook(fam.canon / ".githooks", RETIRED_HOOK)
        g(fam.canon, "config", "core.hooksPath", ".githooks")
        before = fam.remote_main(fam.blessed), fam.remote_main(fam.mirror)

        with pytest.raises(cs.SyncError) as refused:
            cs.publish_base(fam.canon)

        assert refused.value.code == "retired_push_hook"
        assert str(hook.resolve()) in refused.value.detail or str(hook) in refused.value.detail
        assert "install_linear_pre_push.py" in refused.value.detail
        assert "--no-verify" not in refused.value.detail
        assert (fam.remote_main(fam.blessed), fam.remote_main(fam.mirror)) == before
        assert not g(fam.blessed, "for-each-ref", "refs/heads/publish", must=False)
        assert not g(fam.mirror, "for-each-ref", "refs/heads/publish", must=False)

    def test_any_other_refusing_hook_is_named_with_its_output(self, fam):
        cs.land(fam.slot, "feat")
        hook = _hook(fam.canon / ".git" / "hooks", REFUSING_HOOK)
        before = fam.remote_main(fam.blessed)

        with pytest.raises(cs.SyncError) as refused:
            cs.publish_base(fam.canon)

        assert refused.value.code == "publish_failed"
        assert "policy: not today" in refused.value.detail
        assert str(hook) in refused.value.detail or str(hook.resolve()) in refused.value.detail
        assert fam.remote_main(fam.blessed) == before

    def test_publish_works_with_the_linear_hook(self, fam):
        cs.land(fam.slot, "feat")
        _hook(fam.canon / ".git" / "hooks", LINEAR_HOOK.read_text())
        result = cs.publish_base(fam.canon)
        assert result.published == "upstream"
        assert fam.remote_main(fam.blessed) == sha(fam.canon, "refs/heads/main")

    def test_status_reports_the_hook(self, fam, capsys):
        _hook(fam.canon / ".githooks", RETIRED_HOOK)
        g(fam.canon, "config", "core.hooksPath", ".githooks")
        assert cs.main(["status", str(fam.canon)]) == 0
        out = capsys.readouterr().out
        assert "PUSH_HOOK=" in out and "PUSH_HOOK=none" not in out
        assert "PUSH_HOOK_RETIRED=yes" in out

    def test_command_line_reports_the_refusal(self, fam, capsys):
        cs.land(fam.slot, "feat")
        _hook(fam.canon / ".githooks", RETIRED_HOOK)
        g(fam.canon, "config", "core.hooksPath", ".githooks")
        assert cs.main(["publish", str(fam.canon)]) == 1
        out = capsys.readouterr().out
        assert "ERROR=retired_push_hook" in out
        assert "PUBLISHED=" not in out

    @pytest.mark.parametrize("text, expected", [
        ("fatal: unable to access 'https://user:ghp_secret@github.com/o/r.git/'",
         "fatal: unable to access 'https://***@github.com/o/r.git/'"),
        ("error: failed to push some refs to 'https://ghp_secret@github.com/o/r'",
         "error: failed to push some refs to 'https://***@github.com/o/r'"),
        ("to git@github.com:o/r.git", "to git@github.com:o/r.git"),
        ("https://github.com/o/r.git", "https://github.com/o/r.git"),
    ])
    def test_credentials_in_urls_are_never_repeated(self, text, expected):
        assert cs.redact(text) == expected
        assert "ghp_secret" not in cs.redact(text)

    def test_a_failed_push_does_not_leak_the_remote_s_credentials(self, fam):
        cs.land(fam.slot, "feat")
        g(fam.canon, "remote", "set-url", "upstream",
          "https://user:ghp_secret@invalid.invalid/o/r.git")
        with pytest.raises(cs.SyncError) as failed:
            cs.publish_base(fam.canon)
        assert "ghp_secret" not in failed.value.detail
        assert "ghp_secret" not in str(failed.value)


class TestPublishRunsTheBaseBranchsHooks:
    """#568: with hooks tracked in the repo, a feature branch's copy does not
    decide whether the base branch can be published."""

    def _tracked_hooks(self, fam, text: str) -> None:
        _hook(fam.canon / ".githooks", text)
        g(fam.canon, "config", "core.hooksPath", ".githooks")
        g(fam.canon, "add", ".githooks")
        g(fam.canon, "commit", "-q", "-m", "hooks")

    def _feature_branch_with(self, fam, text: str) -> None:
        g(fam.canon, "checkout", "-q", "-b", "feature")
        _hook(fam.canon / ".githooks", text)
        g(fam.canon, "commit", "-q", "-am", "feature keeps another hook")

    def test_stale_hook_on_the_checked_out_feature_branch_does_not_block_main(self, fam):
        self._tracked_hooks(fam, LINEAR_HOOK.read_text())
        self._feature_branch_with(fam, RETIRED_HOOK)
        tree_before = g(fam.canon, "status", "--porcelain"), sha(fam.canon, "HEAD")

        result = cs.publish_base(fam.canon)

        assert result.published == "upstream"
        assert fam.remote_main(fam.blessed) == sha(fam.canon, "refs/heads/main")
        assert (g(fam.canon, "status", "--porcelain"), sha(fam.canon, "HEAD")) == tree_before
        assert (fam.canon / ".githooks" / "pre-push").read_text() == RETIRED_HOOK
        assert g(fam.canon, "config", "--local", "core.hooksPath") == ".githooks"

    def test_retired_hook_on_main_still_refuses_and_names_main(self, fam):
        self._tracked_hooks(fam, RETIRED_HOOK)
        self._feature_branch_with(fam, LINEAR_HOOK.read_text())
        before = fam.remote_main(fam.blessed)

        with pytest.raises(cs.SyncError) as refused:
            cs.publish_base(fam.canon)

        assert refused.value.code == "retired_push_hook"
        assert ".githooks/pre-push on main" in refused.value.detail
        assert fam.remote_main(fam.blessed) == before

    def test_a_refusing_hook_on_main_refuses_even_when_the_feature_branch_has_none(self, fam):
        self._tracked_hooks(fam, REFUSING_HOOK)
        g(fam.canon, "checkout", "-q", "-b", "feature")
        g(fam.canon, "rm", "-q", "-r", ".githooks")
        g(fam.canon, "commit", "-q", "-m", "feature drops hooks")
        before = fam.remote_main(fam.blessed)

        with pytest.raises(cs.SyncError) as refused:
            cs.publish_base(fam.canon)

        assert refused.value.code == "publish_failed"
        assert "policy: not today" in refused.value.detail
        assert fam.remote_main(fam.blessed) == before

    def test_base_branch_checked_out_uses_git_as_configured(self, fam):
        self._tracked_hooks(fam, LINEAR_HOOK.read_text())
        with cs.base_hooks(cs.locate(fam.canon)) as options:
            assert options == []

    def test_no_local_hooks_path_means_no_override(self, fam):
        g(fam.canon, "checkout", "-q", "-b", "feature")
        with cs.base_hooks(cs.locate(fam.canon)) as options:
            assert options == []

    def test_temporary_hooks_are_removed_afterwards(self, fam):
        self._tracked_hooks(fam, LINEAR_HOOK.read_text())
        g(fam.canon, "checkout", "-q", "-b", "feature")
        with cs.base_hooks(cs.locate(fam.canon)) as options:
            where = Path(options[1].split("=", 1)[1])
            assert (where / "pre-push").read_text() == LINEAR_HOOK.read_text()
        assert not where.exists()
