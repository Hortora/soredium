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
