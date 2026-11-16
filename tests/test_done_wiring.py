"""#517: the done-not-closed state is wired into `work next`, the chain engine and ctx.

Before this, `work next` checked the item (closed, in queue terms) without landing
its branch, and the chain engine judged an issue finished only once it was closed
on GitHub, so an issue could not be finished without being closed.
"""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))

import work  # noqa: E402
import work_chain  # noqa: E402
from work_chain import evaluate  # noqa: E402

QUEUE = """# Work Plan —

## State
branch: issue-2-second
status: active
issue-repo: o/r
covers: o/r#2

## Queue
- [ ] o/r#1 — first ← done on issue-1-first
- [ ] o/r#2 — second ← active
- [ ] o/r#3 — third
"""


def _advance_step():
    return next(s for s in work.PIPELINES["next"] if s.name == "advance_issue")


def _ctx(tmp_path, branch, base="main"):
    return SimpleNamespace(plan_path=tmp_path / ".queue", branch=branch, base_branch=base)


class TestWorkNextMarksDone:
    def test_on_a_feature_branch_the_item_is_marked_done_not_closed(self, tmp_path):
        cmd = _advance_step().script_fn(_ctx(tmp_path, "issue-2-second"))
        assert "mark-done" in cmd
        assert "branch=issue-2-second" in cmd
        assert "advance" not in cmd

    def test_on_the_base_branch_there_is_nothing_to_land_so_the_item_is_closed(self, tmp_path):
        cmd = _advance_step().script_fn(_ctx(tmp_path, "main"))
        assert "advance" in cmd
        assert "mark-done" not in cmd

    def test_without_a_queue_the_step_does_nothing(self, tmp_path):
        ctx = _ctx(tmp_path, "issue-2-second")
        ctx.plan_path = None
        assert _advance_step().script_fn(ctx) is None


def _c(**over):
    ctx = {"QUEUE_STATUS": "active", "HAS_QUEUE": "yes", "ACTIVE_ISSUE": "o/r#2",
           "PLAN_POSITION": "0/3", "ON_MAIN": "no", "DONE_PENDING": "0"}
    ctx.update(over)
    return ctx


class TestChainReadsDonenessFromTheQueue:
    def test_next_proceeds_while_the_issue_is_still_open_on_github(self):
        result = evaluate("next", _c(), issue_state="OPEN")
        assert result["DIRECTIVE"] == "proceed"
        assert result["REASON"] == "mark_done"

    def test_next_with_nothing_active_but_items_done_chains_to_end(self):
        result = evaluate("next", _c(ACTIVE_ISSUE="", DONE_PENDING="2"))
        assert result["DIRECTIVE"] == "chain_to_end"
        assert result["REASON"] == "done_items_await_close"

    def test_continue_with_nothing_active_but_items_done_chains_to_end(self):
        result = evaluate("continue", _c(ACTIVE_ISSUE="", DONE_PENDING="1"))
        assert result["DIRECTIVE"] == "chain_to_end"
        assert result["REASON"] == "done_items_await_close"

    def test_end_proceeds_and_reports_the_batch(self):
        result = evaluate("end", _c(DONE_PENDING="2"), issue_state="OPEN")
        assert result["DIRECTIVE"] == "proceed"
        assert result["REASON"] == "batch_close"
        assert result["DONE_PENDING"] == "2"

    def test_end_on_an_open_issue_is_not_blocked(self):
        result = evaluate("end", _c(), issue_state="OPEN")
        assert result["DIRECTIVE"] == "proceed"

    def test_find_is_guarded_while_done_items_await_close(self):
        result = evaluate("find", _c(ACTIVE_ISSUE="", DONE_PENDING="1"))
        assert result["DIRECTIVE"] == "chain_to_end"
        assert result["REASON"] == "done_items_await_close"


class TestWrapOrContinueIsAlwaysOffered:
    @pytest.mark.parametrize("command", ["continue", "next", "end", "find"])
    def test_offered_whenever_done_items_are_pending(self, command):
        result = evaluate(command, _c(DONE_PENDING="1"), issue_state="OPEN")
        assert result["OFFER"] == "wrap_or_continue"

    def test_offered_when_next_finishes_an_item(self):
        assert evaluate("next", _c(), issue_state="OPEN")["OFFER"] == "wrap_or_continue"

    def test_not_offered_when_nothing_is_finished(self):
        assert evaluate("continue", _c(), issue_state="OPEN").get("OFFER", "") == ""


class TestCommandLine:
    """The skill runs the engine as a script; nothing imported it before."""

    def _run(self, tmp_path, command):
        (tmp_path / ".queue").write_text(QUEUE)
        return subprocess.run(
            [sys.executable, str(ROOT / "project" / "work_chain.py"), command,
             f"queue={tmp_path / '.queue'}", "issue_state=OPEN"],
            capture_output=True, text=True)

    def test_prints_a_directive_from_the_queue_file(self, tmp_path):
        r = self._run(tmp_path, "next")
        assert r.returncode == 0, r.stderr
        assert "CHAIN_DIRECTIVE=proceed" in r.stdout
        assert "DONE_PENDING=1" in r.stdout
        assert "DONE_ITEMS=o/r#1@issue-1-first" in r.stdout
        assert "OFFER=wrap_or_continue" in r.stdout

    def test_unknown_command_fails(self, tmp_path):
        r = self._run(tmp_path, "dance")
        assert r.returncode != 0
        assert "ERROR=unknown_command" in r.stdout


class TestCtxReportsPendingItems:
    def test_done_items_are_listed(self, tmp_path):
        (tmp_path / ".queue").write_text(QUEUE)
        import queue_io
        fields = work_chain.done_fields(queue_io.read_queue(tmp_path))
        assert fields == {"DONE_PENDING": "1", "DONE_ITEMS": "o/r#1@issue-1-first"}

    def test_ctx_emits_them(self):
        source = (ROOT / "project" / "ctx.py").read_text()
        assert "done_fields(queue)" in source
