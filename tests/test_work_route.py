#!/usr/bin/env python3
"""project/work_route.py: what `work continue` runs, decided from the queue (#548)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "project"))

from queue_io import Queue, QueueItem, QueueState  # noqa: E402
from work_route import route  # noqa: E402


def item(n, **kw):
    return QueueItem(ref=f"o/r#{n}", title=f"title {n}", completed=False, active=False, **kw)


def queue(*items):
    return Queue(items=list(items), state=QueueState())


def closed(n):
    return QueueItem(ref=f"o/r#{n}", title=f"title {n}", completed=True, active=False)


def active(n):
    return QueueItem(ref=f"o/r#{n}", title=f"title {n}", completed=False, active=True)


class TestActiveItem:
    def test_continue_continues_it(self):
        r = route("continue", queue(active(1), item(2)), "issue-1-x", "main")
        assert (r.run, r.reason, r.issue) == ("continue", "active_work", "o/r#1")
        assert not r.activate and not r.stop

    def test_only_done_marks_the_active_item_done(self):
        q = queue(active(1), item(2))
        r = route("done", q, "issue-1-x", "main")
        assert (r.run, r.reason, r.issue) == ("done", "mark_done", "o/r#1")
        assert r.offer
        assert route("continue", q, "issue-1-x", "main").reason != "mark_done"

    def test_done_with_nothing_active_carries_on_like_continue(self):
        q = queue(closed(1), item(2))
        assert route("done", q, "main", "main") == route("continue", q, "main", "main")

    def test_active_item_with_no_branch_yet_is_started(self):
        """After `done`, the following item is active but has no branch."""
        q = queue(item(1, done_branch="issue-1-x"), active(2))
        r = route("continue", q, "issue-1-x", "main")
        assert (r.run, r.reason, r.issue) == ("start", "active_item_not_started", "o/r#2")
        assert not r.activate
        assert route("continue", queue(active(2)), "main", "main").run == "start"

    def test_active_item_whose_branch_is_not_checked_out_is_a_decision(self):
        q = Queue(items=[active(2)], state=QueueState(branch="issue-2-x"))
        r = route("continue", q, "main", "main")
        assert (r.stop, r.reason) == ("decision", "active_branch_not_checked_out")
        assert "issue-2-x" in r.detail

    def test_active_item_on_its_branch_continues_whatever_the_record_says(self):
        q = Queue(items=[active(2)], state=QueueState(branch=""))
        assert route("continue", q, "issue-2-x", "main").run == "continue"


class TestNothingActiveOnWorkingBranch:
    def test_branch_of_one_open_item_activates_it(self):
        q = queue(closed(1), item(289), item(290))
        r = route("continue", q, "issue-289-deprecated-url", "main")
        assert (r.run, r.activate, r.reason) == ("continue", "o/r#289", "branch_item_activated")

    def test_number_must_match_whole(self):
        q = queue(item(28), item(2890))
        r = route("continue", q, "issue-289-x", "main")
        assert r.stop == "decision"
        assert r.reason == "branch_matches_no_open_item"

    def test_branch_of_no_item_is_a_decision_never_a_guess(self):
        r = route("continue", queue(item(2), item(3)), "wip-experiment", "main")
        assert (r.stop, r.run, r.activate) == ("decision", "", "")

    def test_branch_of_closed_item_is_a_decision(self):
        r = route("continue", queue(closed(1), item(2)), "issue-1-x", "main")
        assert r.stop == "decision"

    def test_same_number_in_two_repos_is_a_decision(self):
        q = Queue(items=[QueueItem("a/b#7", "x", False, False),
                         QueueItem("c/d#7", "y", False, False)], state=QueueState())
        r = route("continue", q, "issue-7-x", "main")
        assert (r.stop, r.reason) == ("decision", "branch_matches_several_items")
        assert "a/b#7" in r.detail and "c/d#7" in r.detail

    def test_still_on_a_finished_items_branch_starts_the_next(self):
        q = queue(item(1, done_branch="issue-1-x"), item(2))
        r = route("continue", q, "issue-1-x", "main")
        assert (r.run, r.activate, r.offer) == ("start", "o/r#2", True)

    def test_on_a_finished_branch_with_nothing_open_goes_to_end(self):
        q = queue(item(1, done_branch="issue-1-x"))
        r = route("continue", q, "issue-1-x", "main")
        assert (r.stop, r.reason) == ("end", "done_items_await_close")


class TestNothingActiveOnBase:
    def test_starts_the_first_open_item(self):
        r = route("continue", queue(closed(1), item(2), item(3)), "main", "main")
        assert (r.run, r.activate, r.issue, r.title) == ("start", "o/r#2", "o/r#2", "title 2")

    def test_skips_done_items_when_choosing(self):
        q = queue(item(1, done_branch="issue-1-x"), item(2))
        r = route("continue", q, "main", "main")
        assert r.activate == "o/r#2"
        assert r.offer

    def test_only_done_items_goes_to_end(self):
        r = route("continue", queue(closed(1), item(2, done_branch="issue-2-x")), "main", "main")
        assert (r.stop, r.run) == ("end", "")
        assert r.offer

    def test_everything_closed_is_nothing(self):
        r = route("continue", queue(closed(1), closed(2)), "main", "main")
        assert (r.stop, r.reason, r.run) == ("nothing", "queue_empty", "")
        assert not r.offer

    def test_empty_queue_is_nothing(self):
        assert route("continue", queue(), "main", "main").stop == "nothing"

    def test_other_base_branch_name(self):
        r = route("continue", queue(item(2)), "trunk", "trunk")
        assert r.run == "start"

    def test_unknown_branch_counts_as_base(self):
        assert route("continue", queue(item(2)), "", "main").run == "start"


class TestPassThrough:
    @pytest.mark.parametrize("command", ["pause", "resume", "find"])
    def test_other_commands_run_as_given(self, command):
        r = route(command, queue(item(2)), "main", "main")
        assert (r.run, r.stop, r.activate) == (command, "", "")

    @pytest.mark.parametrize("command", ["start", "continue", "next"])
    def test_no_queue_runs_the_command_as_given(self, command):
        r = route(command, None, "issue-1-x", "main")
        assert (r.run, r.reason) == (command, "no_queue")

    def test_route_does_not_change_the_queue(self):
        q = queue(closed(1), item(2), item(3, done_branch="issue-3-x"))
        before = repr(q)
        for branch in ("main", "issue-2-x", "issue-3-x", "other"):
            for command in ("start", "continue", "next"):
                route(command, q, branch, "main")
        assert repr(q) == before


class TestMoveOnGate:
    """start and next mean 'move on' — they gate on active work (#596)."""

    def test_start_with_active_item_returns_decision(self):
        q = queue(active(1), item(2))
        r = route("start", q, "issue-1-x", "main")
        assert (r.stop, r.reason) == ("decision", "current_item_not_released")
        assert r.issue == "o/r#1"

    def test_next_with_active_item_returns_decision(self):
        q = queue(active(1), item(2))
        r = route("next", q, "issue-1-x", "main")
        assert (r.stop, r.reason) == ("decision", "current_item_not_released")

    def test_continue_with_active_item_still_carries_on(self):
        q = queue(active(1), item(2))
        r = route("continue", q, "issue-1-x", "main")
        assert (r.run, r.reason) == ("continue", "active_work")

    def test_start_no_active_item_starts_next(self):
        q = queue(closed(1), item(2))
        r = route("start", q, "main", "main")
        assert r.run == "start" and r.activate == "o/r#2"

    def test_next_no_active_item_starts_next(self):
        q = queue(closed(1), item(2))
        r = route("next", q, "main", "main")
        assert r.run == "start" and r.activate == "o/r#2"

    def test_start_active_item_on_base_branch_still_gates(self):
        """On main with an active item that has no branch yet — still a gate."""
        q = queue(active(1), item(2))
        r = route("start", q, "main", "main")
        assert r.stop == "decision"
        assert r.reason == "current_item_not_released"

    def test_start_active_done_on_branch_no_gate(self):
        """Active item is done on its branch — treated as no-active, starts next."""
        q = queue(item(1, done_branch="issue-1-x"), item(2))
        r = route("start", q, "issue-1-x", "main")
        assert r.run == "start" and r.activate == "o/r#2"

    def test_start_and_next_produce_identical_gate(self):
        q = queue(active(1), item(2))
        assert route("start", q, "issue-1-x", "main") == route("next", q, "issue-1-x", "main")

    def test_start_and_next_match_when_no_active(self):
        """Without active work, start and next still behave identically."""
        for q, branch in ((queue(closed(1), item(2)), "main"),
                          (queue(item(2), item(3)), "issue-3-x"),
                          (queue(item(1, done_branch="issue-1-x"), item(2)), "issue-1-x"),
                          (queue(closed(1)), "main")):
            assert route("start", q, branch, "main") == route("next", q, branch, "main")

    def test_gate_has_detail_text(self):
        q = queue(active(1), item(2))
        r = route("start", q, "issue-1-x", "main")
        assert "o/r#1" in r.detail


class TestPausedWork:
    def test_paused_work_comes_before_new_work(self):
        r = route("continue", queue(closed(1), item(2)), "main", "main", stack_depth=2)
        assert (r.run, r.reason, r.activate) == ("resume", "paused_work", "")

    def test_paused_work_does_not_interrupt_an_active_item(self):
        r = route("continue", queue(active(1)), "issue-1-x", "main", stack_depth=2)
        assert r.run == "continue"

    def test_paused_work_is_ignored_off_the_base_branch(self):
        r = route("continue", queue(item(289)), "issue-289-x", "main", stack_depth=1)
        assert (r.run, r.activate) == ("continue", "o/r#289")
