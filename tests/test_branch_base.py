"""Where a working branch starts, and the record of where it did start (#515 stacking)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))

import branch_base  # noqa: E402
from queue_io import read_queue, write_queue, Queue, QueueItem, QueueState  # noqa: E402

BRANCH_CREATE = ROOT / "work-start" / "branch_create.py"
PLAN_MANAGER = ROOT / "work-slot" / "plan_manager.py"


def g(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check).stdout.strip()


def init(path: Path) -> Path:
    path.mkdir(parents=True)
    g(path, "init", "-q", "-b", "main")
    g(path, "config", "user.name", "T")
    g(path, "config", "user.email", "t@t")
    (path / "README.md").write_text("init\n")
    g(path, "add", ".")
    g(path, "commit", "-q", "-m", "init")
    return path


def commit(repo: Path, name: str, message: str = "") -> str:
    (repo / name).write_text(name + "\n")
    g(repo, "add", ".")
    g(repo, "commit", "-q", "-m", message or f"feat: {name}")
    return g(repo, "rev-parse", "HEAD")


def queue(ws: Path, items: list[tuple], active: str) -> None:
    """items: (ref, done_branch, completed, from_main)."""
    write_queue(ws, Queue(
        items=[QueueItem(ref=ref, title=f"title {ref}", completed=completed,
                         active=(ref == active), done_branch=done, from_main=from_main)
               for ref, done, completed, from_main in items],
        state=QueueState(branch="", issue_repo="o/r", status="active"),
    ))


@pytest.fixture
def pair(tmp_path):
    proj = init(tmp_path / "project")
    ws = init(tmp_path / "workspace")
    (ws / "proj").symlink_to(proj)
    return proj, ws


class TestQueueMarker:
    def test_round_trips_through_both_queue_modules(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "", False, False), ("o/r#2", "", False, True)], active="o/r#1")
        text = (ws / ".queue").read_text()
        assert "o/r#2 — title o/r#2 (from main)" in text
        assert "o/r#1 — title o/r#1 (from main)" not in text

        again = read_queue(ws)
        assert [i.from_main for i in again.items] == [False, True]
        assert again.items[1].title == "title o/r#2"

        import plan_manager
        tree = plan_manager.parse_plan(ws / ".queue")
        assert [i.from_main for i in tree.queue] == [False, True]
        plan_manager.rewrite_plan(ws / ".queue", tree)
        assert [i.from_main for i in read_queue(ws).items] == [False, True]

    def test_marker_survives_being_done_and_active(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "b1", False, True), ("o/r#2", "", False, True)], active="o/r#2")
        again = read_queue(ws)
        assert (again.items[0].from_main, again.items[0].done_branch) == (True, "b1")
        assert (again.items[1].from_main, again.items[1].active) == (True, True)

    def test_append_with_base_main_and_set_base(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "", False, False)], active="o/r#1")
        run = lambda *a: subprocess.run([sys.executable, str(PLAN_MANAGER), *a],
                                        capture_output=True, text=True)

        added = run("append", str(ws / ".queue"), "issues=o/r#2:Stands alone", "base=main",
                    "skip-duplicate-check=yes")
        assert added.returncode == 0, added.stdout + added.stderr
        assert read_queue(ws).items[1].from_main is True

        flipped = run("set-base", str(ws / ".queue"), "ref=o/r#2", "base=stack")
        assert "SET_BASE=o/r#2 base=stack" in flipped.stdout
        assert read_queue(ws).items[1].from_main is False

        assert run("set-base", str(ws / ".queue"), "ref=o/r#9", "base=main").returncode == 1

    def test_append_keeps_a_comma_inside_a_title(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "", False, False)], active="o/r#1")
        subprocess.run([sys.executable, str(PLAN_MANAGER), "append", str(ws / ".queue"),
                        "issues=o/r#2:Sync module, close ceremony, slot sweep,o/r#3:Next one",
                        "skip-duplicate-check=yes"], capture_output=True, text=True, check=True)
        titles = [i.title for i in read_queue(ws).items]
        assert titles == ["title o/r#1", "Sync module, close ceremony, slot sweep", "Next one"]


class TestStartPoint:
    def test_first_item_starts_from_the_base_branch(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "", False, False)], active="o/r#1")
        where = branch_base.start_point(ws)
        assert (where.stacked, where.parent) == (False, "")
        assert "first item" in where.reason

    def test_stacks_on_the_finished_item_just_before_it(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "issue-1", False, False), ("o/r#2", "", False, False)], active="o/r#2")
        where = branch_base.start_point(ws)
        assert (where.stacked, where.parent) == (True, "issue-1")

    def test_item_marked_from_main_does_not_stack(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "issue-1", False, False), ("o/r#2", "", False, True)], active="o/r#2")
        where = branch_base.start_point(ws)
        assert where.stacked is False
        assert "(from main)" in where.reason

    def test_does_not_stack_on_an_item_that_already_landed(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "", True, False), ("o/r#2", "", False, False)], active="o/r#2")
        assert branch_base.start_point(ws).stacked is False

    def test_stacks_only_on_the_immediate_predecessor(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "issue-1", False, False), ("o/r#2", "", False, True),
                   ("o/r#3", "", False, False)], active="o/r#3")
        where = branch_base.start_point(ws)
        assert where.stacked is False            # o/r#2 has no finished branch yet
        queue(ws, [("o/r#1", "issue-1", False, False), ("o/r#2", "issue-2", False, True),
                   ("o/r#3", "", False, False)], active="o/r#3")
        assert branch_base.start_point(ws).parent == "issue-2"

    def test_no_queue_starts_from_the_base_branch(self, tmp_path):
        assert branch_base.start_point(tmp_path).stacked is False


class TestRecord:
    def test_own_commits_exclude_what_the_branch_was_stacked_on(self, pair):
        proj, ws = pair
        g(proj, "checkout", "-q", "-b", "issue-1")
        commit(proj, "a.txt")
        tip1 = commit(proj, "b.txt")
        ok, origin = branch_base.cut(proj, "issue-2", "main", "issue-1")
        commit(proj, "c.txt")

        assert (ok, origin) == (True, "issue-1")
        assert branch_base.parent_of(proj, "issue-2") == "issue-1"
        assert branch_base.base_of(proj, "issue-2") == tip1
        assert branch_base.own_commit_count(proj, "issue-2", "main") == 1
        assert g(proj, "rev-list", "--count", "main..issue-2") == "3"

    def test_record_survives_the_parent_being_squashed(self, pair):
        proj, ws = pair
        g(proj, "checkout", "-q", "-b", "issue-1")
        commit(proj, "a.txt")
        tip1 = commit(proj, "b.txt")
        branch_base.cut(proj, "issue-2", "main", "issue-1")
        commit(proj, "c.txt")
        # issue-1 is squashed to one commit: its old commits are no longer on that branch
        g(proj, "checkout", "-q", "issue-1")
        g(proj, "reset", "-q", "--soft", "main")
        g(proj, "commit", "-q", "-m", "feat: a and b")
        assert g(proj, "rev-parse", "issue-1") != tip1

        assert branch_base.base_of(proj, "issue-2") == tip1
        assert branch_base.parent_of(proj, "issue-2") == "issue-1"
        assert branch_base.own_commit_count(proj, "issue-2", "main") == 1

    def test_record_survives_the_branch_itself_being_squashed(self, pair):
        proj, ws = pair
        g(proj, "checkout", "-q", "-b", "issue-1")
        tip1 = commit(proj, "a.txt")
        branch_base.cut(proj, "issue-2", "main", "issue-1")
        commit(proj, "c.txt")
        commit(proj, "d.txt")
        g(proj, "reset", "-q", "--soft", tip1)
        g(proj, "commit", "-q", "-m", "feat: c and d")

        assert branch_base.base_of(proj, "issue-2") == tip1
        assert branch_base.own_commit_count(proj, "issue-2", "main") == 1

    def test_a_record_the_branch_no_longer_sits_on_is_not_trusted(self, pair):
        proj, ws = pair
        g(proj, "checkout", "-q", "-b", "issue-1")
        commit(proj, "a.txt")
        branch_base.cut(proj, "issue-2", "main", "issue-1")
        commit(proj, "c.txt")
        g(proj, "checkout", "-q", "main")
        g(proj, "branch", "-f", "issue-2", "main")

        assert branch_base.base_of(proj, "issue-2") == ""
        assert branch_base.record_is_stale(proj, "issue-2") is True
        assert branch_base.own_range(proj, "issue-2", "main") == "main..issue-2"

    def test_cut_from_the_base_branch_records_no_parent(self, pair):
        proj, ws = pair
        ok, origin = branch_base.cut(proj, "issue-1", "main")
        assert (ok, origin) == (True, "main")
        assert branch_base.parent_of(proj, "issue-1") == ""
        assert branch_base.base_of(proj, "issue-1") == g(proj, "rev-parse", "main")

    def test_parent_missing_in_this_repo_falls_back_to_the_base_branch(self, pair):
        proj, ws = pair
        ok, origin = branch_base.cut(proj, "issue-2", "main", "issue-1")
        assert (ok, origin) == (True, "main")
        assert branch_base.parent_of(proj, "issue-2") == ""


class TestCutGuards:
    """#600: cut() must refuse base-branch names and handle existing branches."""

    def test_refuses_base_branch_name(self, pair):
        proj, ws = pair
        ok, detail = branch_base.cut(proj, "main", "main")
        assert ok is False
        assert "refused" in detail
        assert "main" in detail

    def test_refuses_HEAD(self, pair):
        proj, ws = pair
        ok, detail = branch_base.cut(proj, "HEAD", "main")
        assert ok is False
        assert "refused" in detail

    def test_resumes_known_branch(self, pair):
        proj, ws = pair
        ok, _ = branch_base.cut(proj, "issue-1", "main")
        assert ok is True
        commit(proj, "work.txt")
        g(proj, "checkout", "-q", "main")
        ok, detail = branch_base.cut(proj, "issue-1", "main")
        assert ok is True
        assert detail.startswith("resumed:")
        assert g(proj, "branch", "--show-current") == "issue-1"
        assert (proj / "work.txt").exists()

    def test_resumes_stacked_branch_reports_parent(self, pair):
        proj, ws = pair
        g(proj, "checkout", "-q", "-b", "issue-1")
        commit(proj, "a.txt")
        branch_base.cut(proj, "issue-2", "main", "issue-1")
        g(proj, "checkout", "-q", "main")
        ok, detail = branch_base.cut(proj, "issue-2", "main")
        assert ok is True
        assert detail == "resumed:issue-1"

    def test_refuses_unknown_existing_branch(self, pair):
        proj, ws = pair
        g(proj, "checkout", "-q", "-b", "mystery")
        g(proj, "checkout", "-q", "main")
        ok, detail = branch_base.cut(proj, "mystery", "main")
        assert ok is False
        assert "branch_exists" in detail


class TestCreateBranches:
    def _create(self, proj, ws, branch):
        return subprocess.run(
            [sys.executable, str(BRANCH_CREATE), "create-branches", str(proj), str(ws),
             f"branch={branch}", "base=main"], capture_output=True, text=True)

    def _finish_first(self, proj, ws):
        queue(ws, [("o/r#1", "", False, False), ("o/r#2", "", False, False)], active="o/r#1")
        assert self._create(proj, ws, "issue-1").returncode == 0
        tip_proj = commit(proj, "one.txt")
        tip_ws = commit(ws, "notes-one.md")
        return tip_proj, tip_ws

    def test_next_item_is_stacked_in_every_repo(self, pair):
        proj, ws = pair
        tip_proj, tip_ws = self._finish_first(proj, ws)
        queue(ws, [("o/r#1", "issue-1", False, False), ("o/r#2", "", False, False)], active="o/r#2")

        result = self._create(proj, ws, "issue-2")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACKED=yes" in result.stdout and "STACKED_ON=issue-1" in result.stdout
        assert "CUT_FROM=project:issue-1" in result.stdout
        assert "CUT_FROM=workspace:issue-1" in result.stdout
        assert g(proj, "rev-parse", "issue-2") == tip_proj
        assert g(ws, "rev-parse", "issue-2") == tip_ws
        assert (proj / "one.txt").exists()                  # the earlier item's code is there
        assert branch_base.parent_of(proj, "issue-2") == "issue-1"
        assert branch_base.parent_of(ws, "issue-2") == "issue-1"

    def test_item_marked_from_main_starts_code_from_main_and_keeps_the_queue(self, pair):
        """Code starts from main. The workspace holds the queue file, tracked per branch,
        so it continues from the previous item's branch and the queue's state comes along."""
        proj, ws = pair
        tip_proj, tip_ws = self._finish_first(proj, ws)
        queue(ws, [("o/r#1", "issue-1", False, False), ("o/r#2", "", False, True)], active="o/r#2")

        result = self._create(proj, ws, "issue-2")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACKED=no" in result.stdout
        assert "CUT_FROM=project:main" in result.stdout
        assert "CUT_FROM=workspace:issue-1" in result.stdout
        assert g(proj, "rev-parse", "issue-2") == g(proj, "rev-parse", "main")
        assert not (proj / "one.txt").exists()
        assert branch_base.parent_of(proj, "issue-2") == ""
        assert g(ws, "rev-parse", "issue-2") == tip_ws
        assert branch_base.parent_of(ws, "issue-2") == "issue-1"
        after = read_queue(ws)
        assert (after.items[0].done_branch, after.items[1].active) == ("issue-1", True)

    def test_first_item_records_main_as_its_base(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "", False, False)], active="o/r#1")

        result = self._create(proj, ws, "issue-1")

        assert "STACKED=no" in result.stdout
        assert "first item" in result.stdout
        assert branch_base.base_of(proj, "issue-1") == g(proj, "rev-parse", "main")

    def test_repo_without_the_parent_branch_starts_from_its_base_branch(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "", False, False), ("o/r#2", "", False, False)], active="o/r#1")
        g(proj, "checkout", "-q", "-b", "issue-1")           # the workspace never had issue-1
        commit(proj, "one.txt")
        queue(ws, [("o/r#1", "issue-1", False, False), ("o/r#2", "", False, False)], active="o/r#2")

        result = self._create(proj, ws, "issue-2")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "CUT_FROM=project:issue-1" in result.stdout
        assert "CUT_FROM=workspace:main" in result.stdout

    def test_failure_in_the_workspace_leaves_no_record_behind_in_the_project(self, pair):
        proj, ws = pair
        queue(ws, [("o/r#1", "", False, False)], active="o/r#1")
        g(ws, "branch", "issue-1")                           # already exists: creation fails there

        result = self._create(proj, ws, "issue-1")

        assert result.returncode == 1
        assert "workspace_branch_failed" in result.stdout
        assert g(proj, "branch", "--list", "issue-1") == ""
        assert g(proj, "for-each-ref", "refs/soredium") == ""
