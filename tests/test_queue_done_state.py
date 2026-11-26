"""#517: a queue item can be done but not yet closed.

Done means the work is finished on its branch and the close ceremony has not
run for it. It is written as a suffix on an unchecked item:

    - [ ] owner/repo#1 — title ← done on issue-1-thing

Both queue modules must read it, keep it, and never treat it as closed.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work-slot"))
sys.path.insert(0, str(ROOT / "project"))

import plan_manager  # noqa: E402
import queue_io  # noqa: E402

PLAN_MANAGER = ROOT / "work-slot" / "plan_manager.py"

THREE = """# Work Plan —

## State
branch: issue-1-first
status: active
issue-repo: o/r
covers: o/r#1

## Queue
- [ ] o/r#1 — first ← active
- [ ] o/r#2 — second
- [ ] o/r#3 — third
"""


@pytest.fixture
def ws(tmp_path):
    (tmp_path / ".queue").write_text(THREE)
    return tmp_path


def run(*args):
    return subprocess.run([sys.executable, str(PLAN_MANAGER), *args],
                          capture_output=True, text=True)


def leaves(ws):
    return {str(l.ref): l for l in plan_manager.flatten_leaves(plan_manager.parse_plan(ws / ".queue"))}


class TestMarkDone:
    def test_marks_the_active_item_done_on_the_queue_branch(self, ws):
        r = run("mark-done", str(ws / ".queue"))
        assert r.returncode == 0, r.stdout + r.stderr
        text = (ws / ".queue").read_text()
        assert "- [ ] o/r#1 — first ← done on issue-1-first" in text
        assert "DONE=o/r#1" in r.stdout
        assert "DONE_BRANCH=issue-1-first" in r.stdout

    def test_done_item_is_not_closed(self, ws):
        run("mark-done", str(ws / ".queue"))
        first = leaves(ws)["o/r#1"]
        assert first.completed is False
        assert first.active is False
        assert first.done_branch == "issue-1-first"

    def test_activates_the_next_item_and_clears_the_branch(self, ws):
        r = run("mark-done", str(ws / ".queue"))
        assert leaves(ws)["o/r#2"].active is True
        assert "NEXT=o/r#2" in r.stdout
        state = plan_manager.parse_plan(ws / ".queue").state
        assert state.get("branch", "") == ""
        assert state.get("covers") == "o/r#2"

    def test_explicit_branch_overrides_the_queue_branch(self, ws):
        run("mark-done", str(ws / ".queue"), "branch=other-branch")
        assert leaves(ws)["o/r#1"].done_branch == "other-branch"

    def test_refuses_without_a_branch(self, ws):
        (ws / ".queue").write_text(THREE.replace("branch: issue-1-first", "branch:"))
        r = run("mark-done", str(ws / ".queue"))
        assert r.returncode != 0
        assert "ERROR=no_branch" in r.stdout
        assert "done on" not in (ws / ".queue").read_text()

    def test_refuses_without_an_active_item(self, ws):
        (ws / ".queue").write_text(THREE.replace(" ← active", ""))
        r = run("mark-done", str(ws / ".queue"))
        assert r.returncode != 0
        assert "ERROR=no_active_issue" in r.stdout

    def test_last_item_done_leaves_no_active_item(self, ws):
        for _ in range(2):
            run("mark-done", str(ws / ".queue"))
            run("set-state", str(ws / ".queue"), "key=branch", "value=next-branch")
        r = run("mark-done", str(ws / ".queue"))
        assert "NEXT=none" in r.stdout
        assert not any(l.active for l in leaves(ws).values())
        assert all(l.done_branch for l in leaves(ws).values())

    def test_every_mark_done_offers_wrap_or_continue(self, ws):
        r = run("mark-done", str(ws / ".queue"))
        assert "OFFER=wrap_or_continue" in r.stdout
        assert "DONE_PENDING=1" in r.stdout

    def test_double_call_does_not_mark_next_item_done(self, ws):
        """#630: calling mark-done twice must not mark the newly active item done."""
        r1 = run("mark-done", str(ws / ".queue"))
        assert r1.returncode == 0, r1.stdout + r1.stderr
        r2 = run("mark-done", str(ws / ".queue"), "branch=issue-1-first")
        assert r2.returncode != 0
        assert "ERROR=item_not_started" in r2.stdout
        second = leaves(ws)["o/r#2"]
        assert second.active is True
        assert second.done_branch == ""


class TestDoneSurvivesRewrites:
    def test_plan_manager_rewrite_keeps_the_marker(self, ws):
        run("mark-done", str(ws / ".queue"))
        run("set-state", str(ws / ".queue"), "key=branch", "value=issue-2-second")
        assert "- [ ] o/r#1 — first ← done on issue-1-first" in (ws / ".queue").read_text()

    def test_queue_io_reads_and_rewrites_the_marker(self, ws):
        run("mark-done", str(ws / ".queue"))
        q = queue_io.read_queue(ws)
        first = q.items[0]
        assert (first.completed, first.active, first.done_branch) == (False, False, "issue-1-first")
        assert first.title == "first"
        queue_io.write_queue(ws, q)
        assert leaves(ws)["o/r#1"].done_branch == "issue-1-first"
        assert leaves(ws)["o/r#1"].title == "first"

    def test_ascii_arrow_is_accepted(self, ws):
        (ws / ".queue").write_text(THREE.replace("first ← active", "first <- done on b1"))
        assert leaves(ws)["o/r#1"].done_branch == "b1"
        assert queue_io.read_queue(ws).items[0].done_branch == "b1"


class TestNothingSkipsADoneItemIntoClosed:
    def test_advance_never_activates_a_done_item(self, ws):
        run("mark-done", str(ws / ".queue"))                       # 1 done, 2 active
        run("advance", str(ws / ".queue"))                         # 2 closed, 3 active
        got = leaves(ws)
        assert got["o/r#3"].active is True
        assert got["o/r#1"].done_branch == "issue-1-first" and not got["o/r#1"].completed

    def test_queue_io_activate_next_skips_done_items(self, ws):
        run("mark-done", str(ws / ".queue"))
        q = queue_io.read_queue(ws)
        q.complete_active()
        assert q.has_next() is True
        q.activate_next()
        assert q.active_item().ref == "o/r#3"

    def test_queue_io_has_next_is_false_when_only_done_items_remain(self, ws):
        q = queue_io.read_queue(ws)
        q.items[0].active = False
        for item in q.items:
            item.done_branch = "b"
        assert q.has_next() is False

    def test_queue_io_lists_done_items_in_queue_order(self, ws):
        run("mark-done", str(ws / ".queue"))
        run("set-state", str(ws / ".queue"), "key=branch", "value=issue-2-second")
        run("mark-done", str(ws / ".queue"))
        q = queue_io.read_queue(ws)
        assert [(i.ref, i.done_branch) for i in q.done_items()] == [
            ("o/r#1", "issue-1-first"), ("o/r#2", "issue-2-second")]

    def test_queue_io_complete_closes_one_named_item(self, ws):
        run("mark-done", str(ws / ".queue"))
        q = queue_io.read_queue(ws)
        q.complete("o/r#1")
        queue_io.write_queue(ws, q)
        got = leaves(ws)
        assert got["o/r#1"].completed is True and got["o/r#1"].done_branch == ""
        assert got["o/r#2"].active is True
