"""#517: the done-not-closed state is wired into work next and ctx.

Before this, `work next` checked the item (closed, in queue terms) without landing
its branch. Now it marks done on the branch and the close ceremony lands later.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))

import work  # noqa: E402

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


class TestCtxReportsPendingItems:
    def test_done_items_are_listed(self, tmp_path):
        (tmp_path / ".queue").write_text(QUEUE)
        import queue_io
        from ctx import done_fields
        fields = done_fields(queue_io.read_queue(tmp_path))
        assert fields == {"DONE_PENDING": "1", "DONE_ITEMS": "o/r#1@issue-1-first"}

    def test_ctx_emits_them(self):
        source = (ROOT / "project" / "ctx.py").read_text()
        assert "done_fields(queue)" in source
