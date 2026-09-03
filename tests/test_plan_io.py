#!/usr/bin/env python3
"""Tests for project/plan_io.py — .plan file I/O."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


def _make_plan(tmp_path, content):
    p = tmp_path / ".plan"
    p.write_text(content)
    return p


BASIC_PLAN = """\
# Work Plan — test

## State
branch: issue-42-foo
state: active
date: 2026-08-20
issue-repo: Hortora/soredium
covers: 42

## Queue
- [ ] Hortora/soredium#42 — Fix foo ← active
"""

CROSS_REPO_PLAN = """\
# Work Plan — test

## State
branch: issue-74-design
state: active
date: 2026-08-20
issue-repo: Hortora/soredium
covers: 74

## Queue
- [x] Hortora/soredium#74 — Design session
- [ ] casehubio/blocks#231 — Extract summarisation types ← active
- [ ] casehubio/blocks#233 — Refactor pipeline
"""

PLAN_WITH_UNPARSED = """\
# Work Plan — test

## State
branch: issue-99-test
state: active
covers: 99

## Queue
- [ ] Hortora/soredium#99 — Valid item
- This line doesn't match the regex
- [ ] #100 — Bare issue ref without repo
"""

NO_SECTIONS_PLAN = """\
# Plan
branch: foo
state: active
"""


class TestReadPlan:
    def test_basic_plan(self, tmp_path):
        from plan_io import read_plan
        plan = _make_plan(tmp_path, BASIC_PLAN)
        state = read_plan(plan)
        assert state is not None
        assert state.fields["branch"] == "issue-42-foo"
        assert state.fields["state"] == "active"
        assert state.fields["covers"] == "42"
        assert len(state.queue_items) == 1
        assert state.queue_items[0].repo == "Hortora/soredium"
        assert state.queue_items[0].number == 42
        assert state.queue_items[0].completed is False
        assert state.queue_items[0].active is True
        assert state.unparsed_lines == []

    def test_cross_repo_plan(self, tmp_path):
        from plan_io import read_plan
        plan = _make_plan(tmp_path, CROSS_REPO_PLAN)
        state = read_plan(plan)
        assert len(state.queue_items) == 3
        assert state.queue_items[0].completed is True
        assert state.queue_items[1].repo == "casehubio/blocks"
        assert state.queue_items[1].number == 231
        assert state.queue_items[1].completed is False
        assert state.queue_items[1].active is True
        assert state.queue_items[2].number == 233

    def test_unparsed_lines_tracked(self, tmp_path):
        from plan_io import read_plan
        plan = _make_plan(tmp_path, PLAN_WITH_UNPARSED)
        state = read_plan(plan)
        assert len(state.queue_items) == 2
        assert state.queue_items[0].number == 99
        assert state.queue_items[1].number == 100
        assert state.queue_items[1].repo == ""
        assert len(state.unparsed_lines) == 1
        assert "This line doesn't match" in state.unparsed_lines[0]

    def test_nonexistent_file_returns_none(self, tmp_path):
        from plan_io import read_plan
        assert read_plan(tmp_path / "nonexistent") is None

    def test_plan_without_queue_section(self, tmp_path):
        from plan_io import read_plan
        plan = _make_plan(tmp_path, "# Plan\n\n## State\nbranch: foo\nstate: active\n")
        state = read_plan(plan)
        assert state is not None
        assert state.fields["branch"] == "foo"
        assert state.queue_items == []

    def test_plan_without_state_section(self, tmp_path):
        from plan_io import read_plan
        plan = _make_plan(tmp_path, NO_SECTIONS_PLAN)
        state = read_plan(plan)
        assert state is not None
        assert state.fields["branch"] == "foo"

    def test_epic_and_active_markers(self, tmp_path):
        from plan_io import read_plan
        content = "# Plan\n\n## State\nstate: active\n\n## Queue\n- [ ] org/repo#5 — Big feature (epic) ← active\n"
        plan = _make_plan(tmp_path, content)
        state = read_plan(plan)
        assert len(state.queue_items) == 1
        assert state.queue_items[0].active is True
        assert "epic" not in state.queue_items[0].title.lower()


class TestReadField:
    def test_existing_field(self, tmp_path):
        from plan_io import read_field
        plan = _make_plan(tmp_path, BASIC_PLAN)
        assert read_field(plan, "branch") == "issue-42-foo"
        assert read_field(plan, "state") == "active"

    def test_missing_field(self, tmp_path):
        from plan_io import read_field
        plan = _make_plan(tmp_path, BASIC_PLAN)
        assert read_field(plan, "nonexistent") is None

    def test_nonexistent_file(self, tmp_path):
        from plan_io import read_field
        assert read_field(tmp_path / "nope", "branch") is None


class TestParseCovers:
    def test_single(self):
        from plan_io import parse_covers
        assert parse_covers("42") == [42]

    def test_multiple(self):
        from plan_io import parse_covers
        assert parse_covers("42,19,32") == [42, 19, 32]

    def test_whitespace(self):
        from plan_io import parse_covers
        assert parse_covers(" 42 , 19 , 32 ") == [42, 19, 32]

    def test_empty(self):
        from plan_io import parse_covers
        assert parse_covers("") == []

    def test_non_numeric_skipped(self):
        from plan_io import parse_covers
        assert parse_covers("42,abc,19") == [42, 19]


class TestHasUncompletedItems:
    def test_has_uncompleted(self, tmp_path):
        from plan_io import read_plan, has_uncompleted_items
        plan = _make_plan(tmp_path, CROSS_REPO_PLAN)
        state = read_plan(plan)
        assert has_uncompleted_items(state) is True

    def test_all_completed(self, tmp_path):
        from plan_io import read_plan, has_uncompleted_items
        content = "# Plan\n\n## State\nstate: active\n\n## Queue\n- [x] org/repo#1 — Done\n"
        plan = _make_plan(tmp_path, content)
        state = read_plan(plan)
        assert has_uncompleted_items(state) is False

    def test_empty_queue(self, tmp_path):
        from plan_io import read_plan, has_uncompleted_items
        plan = _make_plan(tmp_path, "# Plan\n\n## State\nstate: active\n\n## Queue\n")
        state = read_plan(plan)
        assert has_uncompleted_items(state) is False


class TestWriteField:
    def test_update_existing_field(self, tmp_path):
        from plan_io import write_field, read_field
        plan = _make_plan(tmp_path, BASIC_PLAN)
        write_field(plan, "state", "closing:review")
        assert read_field(plan, "state") == "closing:review"
        assert read_field(plan, "branch") == "issue-42-foo"

    def test_add_new_field(self, tmp_path):
        from plan_io import write_field, read_field
        plan = _make_plan(tmp_path, BASIC_PLAN)
        write_field(plan, "new-field", "new-value")
        assert read_field(plan, "new-field") == "new-value"
        assert read_field(plan, "state") == "active"

    def test_preserves_queue(self, tmp_path):
        from plan_io import write_field, read_plan
        plan = _make_plan(tmp_path, BASIC_PLAN)
        write_field(plan, "state", "drained")
        state = read_plan(plan)
        assert len(state.queue_items) == 1
        assert state.queue_items[0].number == 42

    def test_atomic_write(self, tmp_path):
        from plan_io import write_field
        plan = _make_plan(tmp_path, BASIC_PLAN)
        write_field(plan, "state", "paused")
        assert not (tmp_path / ".plan.tmp").exists()


class TestWriteFields:
    def test_batch_update(self, tmp_path):
        from plan_io import write_fields, read_plan
        plan = _make_plan(tmp_path, BASIC_PLAN)
        write_fields(plan, {"state": "drained", "branch": "main"})
        state = read_plan(plan)
        assert state.fields["state"] == "drained"
        assert state.fields["branch"] == "main"


class TestRemovePlan:
    def test_removes_file(self, tmp_path):
        from plan_io import remove_plan
        plan = _make_plan(tmp_path, BASIC_PLAN)
        assert plan.exists()
        remove_plan(plan)
        assert not plan.exists()

    def test_nonexistent_is_noop(self, tmp_path):
        from plan_io import remove_plan
        remove_plan(tmp_path / "nonexistent")
