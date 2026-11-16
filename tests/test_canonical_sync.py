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


class TestRemoteMoved:
    def test_remote_ahead_is_pulled_in_and_the_branch_rebased(self, fam):
        theirs = fam.someone_else_pushes({"e.txt": "e1\n"})

        result = cs.land(fam.slot, "feat")

        g(fam.canon, "merge-base", "--is-ancestor", theirs, "main")
        assert g(fam.canon, "rev-list", "--count", f"{theirs}..main") == "2"
        assert result.sha == sha(fam.canon, "refs/heads/main")
        assert result.unpublished == 2
        assert fam.remote_main(fam.blessed) == theirs
        assert merges(fam.canon) == 0

    def test_diverged_canonical_stops_with_nothing_changed(self, fam):
        commit(fam.canon, {"local.txt": "only here\n"}, "local only")
        fam.someone_else_pushes({"e.txt": "e1\n"})
        before = canon_state(fam.canon)
        branch_before = sha(fam.slot, "feat")

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")

        assert raised.value.code == "diverged"
        assert canon_state(fam.canon) == before
        assert sha(fam.slot, "feat") == branch_before

    def test_canonical_ahead_of_remote_lands_on_top_of_its_own_commits(self, fam):
        local_only = commit(fam.canon, {"local.txt": "unpublished\n"}, "local only")

        result = cs.land(fam.slot, "feat")

        g(fam.canon, "merge-base", "--is-ancestor", local_only, "main")
        assert result.unpublished == 3
        assert merges(fam.canon) == 0

    def test_unreachable_remote_refuses_unless_offline(self, fam):
        g(fam.canon, "remote", "set-url", "upstream", str(fam.root / "gone.git"))
        before = canon_state(fam.canon)

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")

        assert raised.value.code == "fetch_failed"
        assert canon_state(fam.canon) == before

    def test_offline_lands_and_says_the_remote_was_not_checked(self, fam):
        g(fam.canon, "remote", "set-url", "upstream", str(fam.root / "gone.git"))

        result = cs.land(fam.slot, "feat", offline=True)

        assert result.sha == sha(fam.slot, "feat") == sha(fam.canon, "refs/heads/main")
        assert "not checked" in result.warnings[0]

    def test_offline_does_not_hide_a_divergence(self, fam):
        commit(fam.canon, {"local.txt": "only here\n"}, "local only")
        fam.someone_else_pushes({"e.txt": "e1\n"})

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat", offline=True)

        assert raised.value.code == "diverged"


class TestRebase:
    def test_conflict_aborts_its_own_rebase_and_changes_nothing(self, fam):
        fam.someone_else_pushes({"a.txt": "theirs\n"})
        branch_before = sha(fam.slot, "feat")

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")

        assert raised.value.code == "rebase_conflict"
        assert "a.txt" in raised.value.detail
        assert sha(fam.slot, "feat") == branch_before
        assert g(fam.slot, "status", "--porcelain") == ""
        assert g(fam.slot, "symbolic-ref", "--short", "HEAD") == "feat"
        assert not (fam.slot / ".git" / "rebase-merge").exists()
        assert g(fam.canon, "rev-list", "--count", "upstream/main..main") == "0"

    def test_rebase_already_in_progress_is_never_aborted(self, fam):
        g(fam.slot, "checkout", "-q", "-b", "clash", "main")
        commit(fam.slot, {"a.txt": "clash\n"}, "clash")
        g(fam.slot, "checkout", "-q", "feat")
        g(fam.slot, "rebase", "clash", must=False)
        assert (fam.slot / ".git" / "rebase-merge").exists()
        fam.someone_else_pushes({"e.txt": "e1\n"})

        with pytest.raises(SyncError) as raised:
            cs.land(fam.slot, "feat")

        assert raised.value.code == "busy"
        assert (fam.slot / ".git" / "rebase-merge").exists()

    def test_branch_not_checked_out_is_rebased_without_switching_anything(self, fam):
        g(fam.slot, "checkout", "-q", "-b", "elsewhere", "main")
        (fam.slot / "b.txt").write_text("uncommitted in slot\n")
        fam.someone_else_pushes({"e.txt": "e1\n"})

        result = cs.land(fam.slot, "feat")

        assert g(fam.slot, "symbolic-ref", "--short", "HEAD") == "elsewhere"
        assert (fam.slot / "b.txt").read_text() == "uncommitted in slot\n"
        assert sha(fam.canon, "refs/heads/main") == result.sha == sha(fam.slot, "feat")
        assert len(g(fam.slot, "worktree", "list").splitlines()) == 1

    def test_dirty_checkout_of_the_branch_refuses_and_changes_nothing(self, fam):
        fam.someone_else_pushes({"e.txt": "e1\n"})
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
        fam.someone_else_pushes({"e.txt": "e1\n"})
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
        fam.someone_else_pushes({"e.txt": "e1\n"})
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

    def test_remote_moved_since_landing_is_a_divergence_and_nothing_is_forced(self, fam):
        cs.land(fam.slot, "feat")
        theirs = fam.someone_else_pushes({"e.txt": "e1\n"})
        before = canon_state(fam.canon)

        with pytest.raises(SyncError) as raised:
            cs.publish_base(fam.canon)

        assert raised.value.code == "diverged"
        assert fam.remote_main(fam.blessed) == theirs
        assert canon_state(fam.canon) == before

    def test_remote_ahead_with_nothing_local_just_catches_canonical_up(self, fam):
        theirs = fam.someone_else_pushes({"e.txt": "e1\n"})

        result = cs.publish_base(fam.canon)

        assert result.pushed == 0
        assert sha(fam.canon, "refs/heads/main") == theirs == fam.remote_main(fam.blessed)

    def test_mirror_failure_warns_and_the_publish_stands(self, fam):
        cs.land(fam.slot, "feat")
        g(fam.canon, "remote", "set-url", "origin", str(fam.root / "gone.git"))

        result = cs.publish_base(fam.canon)

        assert (result.published, result.mirrored) == ("upstream", "failed")
        assert "mirror" in result.warnings[0]
        assert fam.remote_main(fam.blessed) == sha(fam.canon, "refs/heads/main")

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
        assert fam.remote_main(fam.blessed) == sha(fam.canon, "refs/heads/main")

    def test_command_line_reports_a_divergence_as_an_error(self, fam, capsys):
        cs.land(fam.slot, "feat")
        fam.someone_else_pushes({"e.txt": "e1\n"})

        assert cs.main(["publish", str(fam.canon)]) == 1
        assert "ERROR=diverged" in capsys.readouterr().out


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
        fam.someone_else_pushes({"a.txt": "theirs\n"})
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
