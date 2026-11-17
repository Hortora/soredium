"""#517: one close ceremony lands every done item, in queue order, then the active one.

Real git repos, real ceremony. An item is checked only after its own landing and
stamp succeeded, so a failure part-way leaves the rest done-but-not-closed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))

from queue_io import read_queue, write_queue, Queue, QueueItem, QueueState  # noqa: E402
from close import close, render  # noqa: E402
import squash_marker  # noqa: E402


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "commit", "--allow-empty", "-m", "init")
    return path


@pytest.fixture
def repos(tmp_path):
    proj = _init_repo(tmp_path / "project")
    ws = _init_repo(tmp_path / "workspace")
    (ws / "proj").symlink_to(proj)
    return proj, ws


def _branch(repo: Path, name: str, files: dict[str, str], start: str = "main",
            reviewed: bool = True) -> None:
    """Cut a branch from `start` with one commit per file, and leave the repo on main."""
    _git(repo, "checkout", "-b", name, start)
    for fname, content in files.items():
        (repo / fname).write_text(content)
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", f"feat: {name} adds {fname} Refs #1")
    if reviewed:
        squash_marker.mark(repo, name)
    _git(repo, "checkout", "main")


def _queue(ws: Path, items: list[tuple[str, str]], active: str = "", branch: str = "") -> None:
    """items: (ref, done_branch). `active` names the active ref; `branch` is its branch."""
    write_queue(ws, Queue(
        items=[QueueItem(ref=ref, title=f"title {ref}", completed=False,
                         active=(ref == active), done_branch=done)
               for ref, done in items],
        state=QueueState(branch=branch, issue_repo="R", status="active"),
    ))


def _close(proj: Path, ws: Path):
    with patch("close.discover_repo_topology") as m, \
         patch("close._detect_slot_root", return_value=None):
        m.return_value = [(proj, "main", "direct", None, "origin", ""),
                          (ws, "main", "direct", None, "origin", "")]
        return close(ws)


def _main(repo: Path) -> str:
    return _git(repo, "rev-parse", "main").stdout.strip()


def _subjects(repo: Path, since: str) -> list[str]:
    """Commit subjects on main after `since`, oldest first."""
    out = _git(repo, "log", "--reverse", "--format=%s", f"{since}..main").stdout.strip()
    return out.splitlines() if out else []


def _merge_commits(repo: Path, since: str) -> int:
    return len(_git(repo, "rev-list", "--merges", f"{since}..main").stdout.split())


def _state(ws: Path) -> dict[str, tuple[bool, bool, str]]:
    return {i.ref: (i.completed, i.active, i.done_branch) for i in read_queue(ws).items}


def _tip_message(repo: Path, branch: str) -> str:
    return _git(repo, "log", "-1", "--format=%B", branch).stdout


class TestBatchLandsInQueueOrder:

    def test_two_done_items_and_the_active_one_all_land(self, repos):
        proj, ws = repos
        pre = _main(proj)
        _branch(proj, "b1", {"one.txt": "1"})
        _branch(proj, "b2", {"two.txt": "2"})
        _branch(proj, "b3", {"three.txt": "3"})
        _git(proj, "checkout", "b3")
        _queue(ws, [("R#1", "b1"), ("R#2", "b2"), ("R#3", "")], active="R#3", branch="b3")

        result = _close(proj, ws)

        assert result.success, result.errors
        assert _subjects(proj, pre) == ["feat: b1 adds one.txt Refs #1",
                                        "feat: b2 adds two.txt Refs #1",
                                        "feat: b3 adds three.txt Refs #1"]
        assert _merge_commits(proj, pre) == 0
        assert result.closed_items == ["R#1", "R#2", "R#3"]
        assert all(completed for completed, _, _ in _state(ws).values())
        assert read_queue(ws).state.status == "drained"
        assert _git(proj, "branch", "--show-current").stdout.strip() == "main"

    def test_every_branch_is_stamped_with_its_own_issue(self, repos):
        proj, ws = repos
        _branch(proj, "b1", {"one.txt": "1"})
        _branch(proj, "b2", {"two.txt": "2"})
        _queue(ws, [("R#1", "b1"), ("R#2", "b2")])

        assert _close(proj, ws).success

        for branch, issue in (("b1", "R#1"), ("b2", "R#2")):
            message = _tip_message(proj, branch)
            assert message.startswith("chore: branch closed"), message
            assert f"Refs {issue}" in message

    def test_only_done_items_and_nothing_active_drains_the_queue(self, repos):
        proj, ws = repos
        _branch(proj, "b1", {"one.txt": "1"})
        _queue(ws, [("R#1", "b1")])

        result = _close(proj, ws)

        assert result.success, result.errors
        assert result.next_item is None
        assert read_queue(ws).state.status == "drained"

    def test_an_active_item_that_was_never_started_stays_active(self, repos):
        proj, ws = repos
        pre = _main(proj)
        _branch(proj, "b1", {"one.txt": "1"})
        _queue(ws, [("R#1", "b1"), ("R#2", "")], active="R#2", branch="")

        result = _close(proj, ws)

        assert result.success, result.errors
        assert result.closed_items == ["R#1"]
        assert len(_subjects(proj, pre)) == 1
        assert _state(ws)["R#2"] == (False, True, "")
        assert result.next_item is not None and result.next_item.ref == "R#2"
        assert read_queue(ws).state.status == "active"

    def test_a_branch_stacked_on_an_earlier_done_branch_lands_without_duplicates(self, repos):
        proj, ws = repos
        pre = _main(proj)
        _branch(proj, "b1", {"one.txt": "1"})
        _branch(proj, "b2", {"two.txt": "2"}, start="b1")
        _queue(ws, [("R#1", "b1"), ("R#2", "b2")])

        result = _close(proj, ws)

        assert result.success, result.errors
        assert _subjects(proj, pre) == ["feat: b1 adds one.txt Refs #1",
                                        "feat: b2 adds two.txt Refs #1"]
        assert _merge_commits(proj, pre) == 0

    def test_stacked_branch_after_main_moved_does_not_replay_the_earlier_branch(self, repos):
        """The first branch is rebased, so its commits get new SHAs; the second branch
        still carries the old copies and must not land them a second time."""
        proj, ws = repos
        _branch(proj, "b1", {"one.txt": "1", "one-b.txt": "1"})
        _branch(proj, "b2", {"two.txt": "2"}, start="b1")
        (proj / "elsewhere.txt").write_text("x")
        _git(proj, "add", ".")
        _git(proj, "commit", "-m", "feat: landed by someone else Refs #9")
        pre = _main(proj)
        _queue(ws, [("R#1", "b1"), ("R#2", "b2")])

        result = _close(proj, ws)

        assert result.success, result.errors
        assert _subjects(proj, pre) == ["feat: b1 adds one.txt Refs #1",
                                        "feat: b1 adds one-b.txt Refs #1",
                                        "feat: b2 adds two.txt Refs #1"]
        assert _merge_commits(proj, pre) == 0

    def test_main_moved_on_since_the_branches_were_cut(self, repos):
        proj, ws = repos
        _branch(proj, "b1", {"one.txt": "1"})
        _branch(proj, "b2", {"two.txt": "2"})
        (proj / "elsewhere.txt").write_text("x")
        _git(proj, "add", ".")
        _git(proj, "commit", "-m", "feat: landed by someone else Refs #9")
        pre = _main(proj)
        _queue(ws, [("R#1", "b1"), ("R#2", "b2")])

        result = _close(proj, ws)

        assert result.success, result.errors
        assert len(_subjects(proj, pre)) == 2
        assert _merge_commits(proj, pre) == 0


class TestNothingLandsWhenTheBatchIsNotReady:

    def test_one_unreviewed_branch_holds_back_the_whole_batch(self, repos):
        proj, ws = repos
        pre = _main(proj)
        _branch(proj, "b1", {"one.txt": "1"})
        _branch(proj, "b2", {"two.txt": "2", "two-b.txt": "2"}, reviewed=False)
        _queue(ws, [("R#1", "b1"), ("R#2", "b2")])

        result = _close(proj, ws)

        assert not result.success
        assert any("b2" in r for r in result.squash_review)
        assert _main(proj) == pre
        assert _state(ws) == {"R#1": (False, False, "b1"), "R#2": (False, False, "b2")}

    def test_a_done_item_whose_branch_exists_nowhere_is_an_error(self, repos):
        proj, ws = repos
        pre = _main(proj)
        _branch(proj, "b1", {"one.txt": "1"})
        _queue(ws, [("R#1", "b1"), ("R#2", "gone")])

        result = _close(proj, ws)

        assert not result.success
        assert any("R#2" in e and "gone" in e for e in result.errors), result.errors
        assert _main(proj) == pre
        assert _state(ws)["R#1"] == (False, False, "b1")


class TestFailurePartWay:

    def _conflicting(self, repos):
        proj, ws = repos
        _branch(proj, "b1", {"same.txt": "from b1"})
        _branch(proj, "b2", {"same.txt": "from b2"})
        _branch(proj, "b3", {"three.txt": "3"})
        _queue(ws, [("R#1", "b1"), ("R#2", "b2"), ("R#3", "b3")])
        return proj, ws

    def test_items_before_the_failure_are_closed_and_the_rest_stay_done(self, repos):
        proj, ws = self._conflicting(repos)
        pre = _main(proj)

        with pytest.raises(RuntimeError):
            _close(proj, ws)

        assert _subjects(proj, pre) == ["feat: b1 adds same.txt Refs #1"]
        state = _state(ws)
        assert state["R#1"][0] is True
        assert state["R#2"] == (False, False, "b2")
        assert state["R#3"] == (False, False, "b3")

    def test_repos_are_left_on_the_base_branch_with_no_rebase_in_progress(self, repos):
        proj, ws = self._conflicting(repos)

        with pytest.raises(RuntimeError):
            _close(proj, ws)

        assert _git(proj, "branch", "--show-current").stdout.strip() == "main"
        assert not (proj / ".git" / "rebase-merge").exists()
        assert _git(proj, "status", "--porcelain").stdout.strip() == ""

    def test_progress_is_committed_in_the_workspace(self, repos):
        proj, ws = self._conflicting(repos)

        with pytest.raises(RuntimeError):
            _close(proj, ws)

        committed = _git(ws, "show", "HEAD:.queue").stdout
        assert "- [x] R#1" in committed
        assert "done on b2" in committed

    def test_a_rerun_closes_an_item_whose_branch_was_already_stamped(self, repos):
        proj, ws = repos
        _branch(proj, "b1", {"one.txt": "1"})
        _queue(ws, [("R#1", "b1")])
        assert _close(proj, ws).success
        _queue(ws, [("R#1", "b1")])          # the queue write was lost; the stamp was not
        pre = _main(proj)

        result = _close(proj, ws)

        assert result.success, result.errors
        assert _main(proj) == pre
        assert _state(ws)["R#1"][0] is True


class TestRendering:

    def test_each_closed_item_is_reported_for_issue_closure(self, repos):
        proj, ws = repos
        _branch(proj, "b1", {"one.txt": "1"})
        _branch(proj, "b2", {"two.txt": "2"})
        _queue(ws, [("R#1", "b1"), ("R#2", "b2")])

        lines = render(_close(proj, ws))

        assert "CLOSED_ITEM=R#1 branch=b1" in lines
        assert "CLOSED_ITEM=R#2 branch=b2" in lines
        assert lines.index("CLOSED_ITEM=R#1 branch=b1") < lines.index("CLOSED_ITEM=R#2 branch=b2")


# --- #526: a real remote, with local main ahead of it ---

def _with_remote(tmp_path: Path, proj: Path) -> Path:
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    _git(proj, "remote", "add", "origin", str(bare))
    _git(proj, "push", "-q", "origin", "main")
    return bare


class TestLocalBaseAheadOfRemote:
    """Fixtures without a remote hid this: the rebase targeted the remote-tracking
    base and ignored a local base that had moved on."""

    def test_two_branches_cut_from_the_pushed_base_both_land(self, repos, tmp_path):
        proj, ws = repos
        _with_remote(tmp_path, proj)
        pre = _main(proj)
        _branch(proj, "b1", {"one.txt": "1"})
        _branch(proj, "b2", {"two.txt": "2"})
        _queue(ws, [("R#1", "b1"), ("R#2", "b2")])

        result = _close(proj, ws)

        assert result.success, result.errors
        assert _subjects(proj, pre) == ["feat: b1 adds one.txt Refs #1",
                                        "feat: b2 adds two.txt Refs #1"]
        assert _merge_commits(proj, pre) == 0

    def test_single_branch_lands_when_local_main_has_unpushed_commits(self, repos, tmp_path):
        proj, ws = repos
        _with_remote(tmp_path, proj)
        _branch(proj, "b1", {"one.txt": "1"})
        (proj / "local-only.txt").write_text("x")
        _git(proj, "add", ".")
        _git(proj, "commit", "-m", "feat: landed locally, not pushed Refs #9")
        pre = _main(proj)
        _queue(ws, [("R#1", "b1")])

        result = _close(proj, ws)

        assert result.success, result.errors
        assert _subjects(proj, pre) == ["feat: b1 adds one.txt Refs #1"]
        assert _git(proj, "show", "main:local-only.txt").stdout == "x"

    def test_remote_ahead_of_local_main_lands_without_fetching_it(self, repos, tmp_path):
        proj, ws = repos
        bare = _with_remote(tmp_path, proj)
        _branch(proj, "b1", {"one.txt": "1"})
        other = tmp_path / "other"
        subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)
        _git(other, "config", "user.email", "o@test.com")
        _git(other, "config", "user.name", "Other")
        (other / "remote-only.txt").write_text("r")
        _git(other, "add", ".")
        _git(other, "commit", "-m", "feat: pushed by someone else Refs #9")
        _git(other, "push", "-q", "origin", "main")
        _queue(ws, [("R#1", "b1")])

        result = _close(proj, ws)

        # Landing is on disk: the remote's new commit arrives when publishing, not here.
        assert result.success, result.errors
        assert _git(proj, "show", "main:one.txt").stdout == "1"
        assert _git(proj, "show", "main:remote-only.txt", check=False).returncode != 0
        assert _merge_commits(proj, "HEAD~1") == 0

    def test_diverged_local_and_remote_base_lands_then_publish_settles_it(self, repos, tmp_path):
        proj, ws = repos
        bare = _with_remote(tmp_path, proj)
        _branch(proj, "b1", {"one.txt": "1"})
        other = tmp_path / "other"
        subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)
        _git(other, "config", "user.email", "o@test.com")
        _git(other, "config", "user.name", "Other")
        (other / "remote-only.txt").write_text("r")
        _git(other, "add", ".")
        _git(other, "commit", "-m", "feat: pushed by someone else Refs #9")
        _git(other, "push", "-q", "origin", "main")
        (proj / "local-only.txt").write_text("x")
        _git(proj, "add", ".")
        _git(proj, "commit", "-m", "feat: landed locally, not pushed Refs #9")
        pre = _main(proj)
        _queue(ws, [("R#1", "b1")])

        result = _close(proj, ws)

        # Landing does not look at the remote; publishing puts the unpublished
        # commits on top of what the remote gained.
        assert result.success, result.errors
        assert _subjects(proj, pre) == ["feat: b1 adds one.txt Refs #1"]
        import canonical_sync
        published = canonical_sync.publish_base(proj)
        assert published.rebased == 2
        assert _git(proj, "show", "main:remote-only.txt").stdout == "r"
        assert _git(proj, "show", "main:local-only.txt").stdout == "x"
        assert _git(proj, "show", "main:one.txt").stdout == "1"
        assert _git(bare, "rev-parse", "main").stdout.strip() == _main(proj)
        assert _git(proj, "rev-list", "--merges", "--count", "main").stdout.strip() == "0"


class TestLandsOnDiskOnly:
    """#515: the ceremony lands in canonical and pushes nothing; publishing is offered."""

    @pytest.fixture
    def published(self, repos, tmp_path):
        proj, ws = repos
        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)],
                       capture_output=True, check=True)
        _git(proj, "remote", "add", "origin", str(remote))
        _git(proj, "push", "-q", "origin", "main")
        _git(proj, "fetch", "-q", "origin")
        return proj, ws, remote

    def _remote_main(self, remote: Path) -> str:
        return _git(remote, "rev-parse", "main").stdout.strip()

    def test_nothing_is_pushed_and_publishing_is_offered(self, published):
        proj, ws, remote = published
        before = self._remote_main(remote)
        _branch(proj, "issue-1-a", {"a.txt": "a", "b.txt": "b"})
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")

        result = _close(proj, ws)

        assert result.success, result.errors
        assert self._remote_main(remote) == before
        assert result.unpublished == {str(proj.resolve()): 2}
        lines = render(result)
        assert f"UNPUBLISHED={proj.resolve()} commits=2" in lines
        assert "OFFER=publish" in lines

    def test_publish_command_then_puts_it_on_the_remote(self, published):
        import canonical_sync
        proj, ws, remote = published
        _branch(proj, "issue-1-a", {"a.txt": "a"})
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")
        _close(proj, ws)

        assert canonical_sync.main(["publish", str(proj)]) == 0

        assert self._remote_main(remote) == _git(proj, "rev-parse", "main").stdout.strip()

    def test_no_offer_when_the_repo_has_no_remote(self, repos):
        proj, ws = repos
        _branch(proj, "issue-1-a", {"a.txt": "a"})
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")

        result = _close(proj, ws)

        assert result.success, result.errors
        assert "OFFER=publish" not in render(result)

    def test_reported_sha_is_the_tip_of_main(self, repos):
        """casehub-pages#666 bug 3: no commit is added to main after the landing."""
        proj, ws = repos
        _git(proj, "checkout", "-b", "issue-1-a")
        (proj / "a.txt").write_text("a")
        (proj / ".close-state").write_text("leaked\n")
        _git(proj, "add", "-A", "-f")
        _git(proj, "commit", "-m", "feat: a with a leaked lifecycle file Refs #1")
        _git(proj, "checkout", "main")
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")

        result = _close(proj, ws)

        assert result.success, result.errors
        main = _git(proj, "rev-parse", "main").stdout.strip()
        assert result.landed["project"] == main
        assert _git(proj, "ls-tree", "--name-only", "main", "--", ".close-state").stdout == ""
        assert (proj / "a.txt").exists()

    def test_unreachable_remote_makes_no_difference_to_landing(self, published, tmp_path):
        proj, ws, remote = published
        _git(proj, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
        _branch(proj, "issue-1-a", {"a.txt": "a"})
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")

        result = _close(proj, ws)

        assert result.success, result.errors
        assert result.warnings == []
        assert _git(proj, "rev-parse", "main").stdout.strip() == result.landed["project"]

    def test_a_failed_landing_leaves_every_checkout_where_it_was(self, repos):
        proj, ws = repos
        _branch(proj, "issue-1-a", {"a.txt": "branch"})
        (proj / "a.txt").write_text("main")
        _git(proj, "add", ".")
        _git(proj, "commit", "-m", "feat: main changes a Refs #1")
        _git(proj, "checkout", "-b", "other-work")
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")
        squash_marker.mark(proj, "issue-1-a")

        try:
            result = _close(proj, ws)
            failed = not result.success
        except RuntimeError:
            failed = True

        assert failed
        assert _git(proj, "branch", "--show-current").stdout.strip() == "other-work"
        assert not (proj / ".git" / "rebase-merge").exists()

    def test_slot_clone_with_no_canonical_is_refused_before_anything_changes(self, repos, tmp_path):
        proj, ws = repos
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / ".slot").write_text("# Slot\n")
        clone = slot / "project"
        subprocess.run(["git", "clone", "-q", str(proj), str(clone)],
                       capture_output=True, check=True)
        _git(clone, "config", "user.email", "test@test.com")
        _git(clone, "config", "user.name", "Test")
        _git(clone, "remote", "remove", "origin")
        _branch(clone, "issue-1-a", {"a.txt": "a", ".close-state": "x"})
        tip = _git(clone, "rev-parse", "issue-1-a").stdout.strip()
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")

        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [(clone, "main", "two-hop", None, "origin", "")]
            result = close(ws)

        assert not result.success
        assert any("no `local` remote" in e for e in result.errors)
        assert _git(clone, "rev-parse", "issue-1-a").stdout.strip() == tip


class TestPromotionGate:
    """A branch is not closed while documents it wrote are still only in the workspace."""

    def _workspace_doc(self, ws: Path, branch: str, rel: str, text: str = "content\n") -> None:
        _git(ws, "checkout", "-q", "-b", branch)
        path = ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        _git(ws, "add", ".")
        _git(ws, "commit", "-q", "-m", f"docs: {rel} Refs #1")

    def _on_branches(self, proj: Path, ws: Path, branch: str, doc: str):
        _git(proj, "checkout", "-q", "-b", branch)
        (proj / "code.txt").write_text("code")
        _git(proj, "add", ".")
        _git(proj, "commit", "-q", "-m", "feat: code Refs #1")
        self._workspace_doc(ws, branch, doc)
        _queue(ws, [("R#1", "")], active="R#1", branch=branch)

    def test_refuses_and_names_the_document_and_the_command(self, repos):
        proj, ws = repos
        self._on_branches(proj, ws, "issue-1-a", "blog/2026-01-01-entry.md")
        main_before = _git(proj, "rev-parse", "main").stdout.strip()

        result = _close(proj, ws)

        assert not result.success
        assert result.unpromoted == [
            "workspace/blog/2026-01-01-entry.md -> project/docs/blog/2026-01-01-entry.md"]
        lines = render(result)
        assert lines[0] == "ACTION=promotion_needed"
        assert any(l.startswith("PROMOTE=python3 ") and "scope=branch" in l for l in lines)
        assert _git(proj, "rev-parse", "main").stdout.strip() == main_before
        assert _state(ws)["R#1"][0] is False

    def test_running_the_named_command_then_closing_lands_the_document(self, repos):
        proj, ws = repos
        self._on_branches(proj, ws, "issue-1-a", "blog/2026-01-01-entry.md")
        command = [l for l in render(_close(proj, ws)) if l.startswith("PROMOTE=")][0]

        promoted = subprocess.run(command[len("PROMOTE="):].split(), capture_output=True, text=True)
        assert promoted.returncode == 0, promoted.stdout + promoted.stderr
        assert "PROMOTED=1" in promoted.stdout and "REMAINING=0" in promoted.stdout
        squash_marker.mark(proj, "issue-1-a")

        result = _close(proj, ws)

        assert result.success, (result.errors, result.unpromoted, result.squash_review)
        assert _git(proj, "show", "main:docs/blog/2026-01-01-entry.md").stdout == "content\n"

    def test_spec_in_a_subdirectory_is_gated_too(self, repos):
        proj, ws = repos
        self._on_branches(proj, ws, "issue-1-a", "specs/issue-1-a/design.md")

        result = _close(proj, ws)

        assert result.unpromoted == [
            "workspace/specs/issue-1-a/design.md -> project/docs/specs/issue-1-a/design.md"]

    def test_backlog_from_before_this_work_does_not_block(self, repos):
        proj, ws = repos
        (ws / "blog").mkdir()
        (ws / "blog" / "2020-old-entry.md").write_text("never promoted\n")
        _git(ws, "add", ".")
        _git(ws, "commit", "-q", "-m", "docs: old entry Refs #1")
        _branch(proj, "issue-1-a", {"a.txt": "a"})
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")

        result = _close(proj, ws)

        assert result.success, (result.errors, result.unpromoted)

    def test_document_already_in_the_project_passes(self, repos):
        proj, ws = repos
        self._on_branches(proj, ws, "issue-1-a", "blog/2026-01-01-entry.md")
        (proj / "docs" / "blog").mkdir(parents=True)
        (proj / "docs" / "blog" / "2026-01-01-entry.md").write_text("content\n")
        _git(proj, "add", ".")
        _git(proj, "commit", "-q", "-m", "docs: promote entry Refs #1")
        squash_marker.mark(proj, "issue-1-a")

        result = _close(proj, ws)

        assert result.success, (result.errors, result.unpromoted, result.squash_review)

    def test_plans_and_images_alone_do_not_block(self, repos):
        proj, ws = repos
        _git(proj, "checkout", "-q", "-b", "issue-1-a")
        (proj / "code.txt").write_text("code")
        _git(proj, "add", ".")
        _git(proj, "commit", "-q", "-m", "feat: code Refs #1")
        self._workspace_doc(ws, "issue-1-a", "plans/2026-01-01-plan.md")
        (ws / "blog" / "images").mkdir(parents=True)
        (ws / "blog" / "images" / "pic.svg").write_text("<svg/>")
        _git(ws, "add", ".")
        _git(ws, "commit", "-q", "-m", "docs: image Refs #1")
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")

        result = _close(proj, ws)

        assert result.unpromoted == []

    def test_promotion_is_asked_for_before_the_squash_review(self, repos):
        """Promoting adds a commit; the review must be of the branch as it will land."""
        proj, ws = repos
        _git(proj, "checkout", "-q", "-b", "issue-1-a")
        for name in ("a.txt", "b.txt"):
            (proj / name).write_text(name)
            _git(proj, "add", ".")
            _git(proj, "commit", "-q", "-m", f"feat: {name} Refs #1")
        self._workspace_doc(ws, "issue-1-a", "blog/2026-01-01-entry.md")
        _queue(ws, [("R#1", "")], active="R#1", branch="issue-1-a")

        result = _close(proj, ws)

        assert render(result)[0] == "ACTION=promotion_needed"


class TestSweepReportsFailure:
    def test_a_rejected_promotion_commit_is_an_error_not_a_silent_success(self, repos):
        proj, ws = repos
        hook = proj / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\necho 'commit needs an issue reference' >&2\nexit 1\n")
        hook.chmod(0o755)
        _git(ws, "checkout", "-q", "-b", "issue-1-a")
        (ws / "blog").mkdir()
        (ws / "blog" / "2026-01-01-entry.md").write_text("content\n")
        _git(ws, "add", ".")
        _git(ws, "commit", "-q", "-m", "docs: entry")
        sweep = Path(__file__).parent.parent / "work-end" / "artifact_sweep.py"

        result = subprocess.run([sys.executable, str(sweep), str(ws), str(proj), "scope=branch"],
                                capture_output=True, text=True)

        assert result.returncode == 1
        assert "ERROR=commit_failed" in result.stdout
        assert "issue reference" in result.stdout
        assert "PROMOTED=0" in result.stdout
