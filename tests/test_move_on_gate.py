#!/usr/bin/env python3
"""Integration tests for the move-on gate (#596).

Verifies the full flow: route returns gate decision, option chosen,
plan_manager executes, re-route picks the next item.
"""
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))

from queue_io import Queue, QueueItem, QueueState  # noqa: E402
from work_route import route  # noqa: E402
import plan_manager  # noqa: E402


def item(n, **kw):
    return QueueItem(ref=f"o/r#{n}", title=f"title {n}", completed=False, active=False, **kw)


def queue(*items):
    return Queue(items=list(items), state=QueueState())


def closed(n):
    return QueueItem(ref=f"o/r#{n}", title=f"title {n}", completed=True, active=False)


def active(n):
    return QueueItem(ref=f"o/r#{n}", title=f"title {n}", completed=False, active=True)


def write_queue(tmp_path, content):
    (tmp_path / ".queue").write_text(textwrap.dedent(content))


class TestGateTable:
    """Each row of the gate table from #596."""

    def test_no_active_item_starts_next(self):
        q = queue(closed(1), item(2))
        for cmd in ("start", "next"):
            r = route(cmd, q, "main", "main")
            assert r.run == "start"
            assert r.stop == ""

    def test_done_item_starts_next(self):
        q = queue(item(1, done_branch="issue-1-x"), item(2))
        for cmd in ("start", "next"):
            r = route(cmd, q, "issue-1-x", "main")
            assert r.run == "start"
            assert r.activate == "o/r#2"

    def test_active_item_gates(self):
        q = queue(active(1), item(2))
        for cmd in ("start", "next"):
            r = route(cmd, q, "issue-1-x", "main")
            assert r.stop == "decision"
            assert r.reason == "current_item_not_released"

    def test_continue_does_not_gate(self):
        q = queue(active(1), item(2))
        r = route("continue", q, "issue-1-x", "main")
        assert r.run == "continue"
        assert r.stop == ""


class TestGateOptions:
    """After the gate fires, each option leads to the right outcome."""

    def test_done_marks_done_then_next_starts(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — first item ← active
            - [ ] o/r#2 — second item
        """)
        result = plan_manager.mark_done(tmp_path / ".queue", branch="issue-1-x")
        assert str(result["done"]) == "o/r#1"
        assert str(result["next"]) == "o/r#2"
        from queue_io import read_queue
        q = read_queue(tmp_path)
        r = route("continue", q, "issue-1-x", "main")
        assert r.run == "start" and r.issue == "o/r#2"

    def test_deferred_removes_then_next_starts(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — first item ← active
            - [ ] o/r#2 — second item
        """)
        result = plan_manager.defer_active(tmp_path / ".queue", reason="not ready")
        assert result["deferred"] == "o/r#1"
        assert result["next"] == "o/r#2"
        from queue_io import read_queue
        q = read_queue(tmp_path)
        active_item = q.active_item()
        assert active_item is not None
        assert active_item.ref == "o/r#2"

    def test_move_down_repositions_then_next_starts(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — first item ← active
            - [ ] o/r#2 — second item
            - [ ] o/r#3 — third item
        """)
        result = plan_manager.move_down(tmp_path / ".queue", position="end")
        assert result["moved"] == "o/r#1"
        assert result["next"] == "o/r#2"
        from queue_io import read_queue
        q = read_queue(tmp_path)
        assert q.active_item().ref == "o/r#2"
        refs = [i.ref for i in q.items if not i.completed]
        assert refs[-1] == "o/r#1"

    def test_continue_option_carries_on(self):
        q = queue(active(1), item(2))
        r = route("continue", q, "issue-1-x", "main")
        assert r.run == "continue"
        assert r.reason == "active_work"


class TestStartNextEquivalence:
    """start and next are equivalent at every state."""

    def test_both_gate_on_active(self):
        q = queue(active(1), item(2))
        assert route("start", q, "issue-1-x", "main") == route("next", q, "issue-1-x", "main")

    def test_both_start_next_when_no_active(self):
        q = queue(closed(1), item(2))
        assert route("start", q, "main", "main") == route("next", q, "main", "main")

    def test_both_resume_on_paused_stack(self):
        q = queue(closed(1), item(2))
        r_s = route("start", q, "main", "main", stack_depth=2)
        r_n = route("next", q, "main", "main", stack_depth=2)
        assert r_s == r_n

    def test_both_end_when_only_done_items(self):
        q = queue(item(1, done_branch="issue-1-x"))
        assert route("start", q, "main", "main") == route("next", q, "main", "main")
