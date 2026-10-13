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


class TestCoverRef:
    def test_bare_number_str(self):
        from plan_io import CoverRef
        ref = CoverRef(number=42)
        assert str(ref) == "42"
        assert int(ref) == 42

    def test_qualified_str(self):
        from plan_io import CoverRef
        ref = CoverRef(number=276, repo="casehubio/platform")
        assert str(ref) == "casehubio/platform#276"
        assert int(ref) == 276

    def test_empty_repo_is_bare(self):
        from plan_io import CoverRef
        ref = CoverRef(number=99, repo="")
        assert str(ref) == "99"


class TestParseCoversQualified:
    def test_bare_numbers(self):
        from plan_io import parse_covers_qualified
        result = parse_covers_qualified("42,19")
        assert len(result) == 2
        assert result[0].number == 42
        assert result[0].repo == ""
        assert result[1].number == 19

    def test_qualified_refs(self):
        from plan_io import parse_covers_qualified
        result = parse_covers_qualified("casehubio/platform#276,casehubio/engine#1049")
        assert len(result) == 2
        assert result[0].number == 276
        assert result[0].repo == "casehubio/platform"
        assert result[1].number == 1049
        assert result[1].repo == "casehubio/engine"

    def test_mixed_bare_and_qualified(self):
        from plan_io import parse_covers_qualified
        result = parse_covers_qualified("42,casehubio/engine#1049,19")
        assert len(result) == 3
        assert result[0].number == 42
        assert result[0].repo == ""
        assert result[1].number == 1049
        assert result[1].repo == "casehubio/engine"
        assert result[2].number == 19

    def test_empty_string(self):
        from plan_io import parse_covers_qualified
        assert parse_covers_qualified("") == []

    def test_whitespace_handling(self):
        from plan_io import parse_covers_qualified
        result = parse_covers_qualified(" 42 , casehubio/engine#100 ")
        assert len(result) == 2
        assert result[0].number == 42
        assert result[1].number == 100
        assert result[1].repo == "casehubio/engine"

    def test_unrecognised_format_skipped(self):
        from plan_io import parse_covers_qualified
        result = parse_covers_qualified("42,platform:276,19")
        assert len(result) == 2
        assert result[0].number == 42
        assert result[1].number == 19

    def test_dots_and_hyphens_in_repo(self):
        from plan_io import parse_covers_qualified
        result = parse_covers_qualified("my-org.io/my-repo.v2#55")
        assert len(result) == 1
        assert result[0].repo == "my-org.io/my-repo.v2"
        assert result[0].number == 55


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


class TestUpdateLifecycleFields:
    def test_updates_state_preserves_queue(self, tmp_path):
        from plan_io import update_lifecycle_fields, read_plan
        plan = _make_plan(tmp_path, (
            "## State\n"
            "state: active\n"
            "branch: issue-42-feature\n"
            "covers: 42\n"
            "\n"
            "## Queue\n"
            "- [x] hortora/soredium#42 — implement widget ← active\n"
            "- [ ] hortora/soredium#43 — add tests\n"
        ))
        update_lifecycle_fields(plan, state="closing:review")
        content = plan.read_text()
        assert "state: closing:review" in content
        assert "branch: issue-42-feature" in content
        state = read_plan(plan)
        assert len(state.queue_items) == 2

    def test_adds_evidence_era(self, tmp_path):
        from plan_io import update_lifecycle_fields
        plan = _make_plan(tmp_path, (
            "## State\n"
            "state: active\n"
            "branch: issue-42-feature\n"
        ))
        update_lifecycle_fields(plan, state="closing:review", evidence_era=True)
        content = plan.read_text()
        assert "state: closing:review" in content
        assert "evidence-era: true" in content

    def test_only_updates_lifecycle_fields(self, tmp_path):
        from plan_io import update_lifecycle_fields
        plan = _make_plan(tmp_path, (
            "## State\n"
            "state: active\n"
            "branch: issue-42-feature\n"
            "design-repo: casehubio/platform\n"
            "flyway-next-v: V042\n"
            "\n"
            "## Deferred\n"
            "- S: refactor the widget\n"
        ))
        update_lifecycle_fields(plan, state="closing:verified")
        content = plan.read_text()
        assert "state: closing:verified" in content
        assert "design-repo: casehubio/platform" in content
        assert "flyway-next-v: V042" in content
        assert "## Deferred" in content
        assert "refactor the widget" in content


class TestCopyPlan:
    def test_copies_content(self, tmp_path):
        from plan_io import copy_plan
        src = tmp_path / "src.plan"
        dst = tmp_path / "dst.plan"
        content = "## State\nstate: active\nbranch: test\n\n## Queue\n- [ ] hortora/soredium#42 — work\n"
        src.write_text(content)
        copy_plan(src, dst)
        assert dst.read_text() == content
        assert not (tmp_path / "dst.plan.tmp").exists()

    def test_overwrites_existing_dst(self, tmp_path):
        from plan_io import copy_plan
        src = tmp_path / "src.plan"
        dst = tmp_path / "dst.plan"
        src.write_text("## State\nstate: new\n")
        dst.write_text("## State\nstate: old\n")
        copy_plan(src, dst)
        assert "state: new" in dst.read_text()


class TestWritePlan:
    def test_writes_valid_content(self, tmp_path):
        from plan_io import write_plan
        plan = tmp_path / ".plan"
        content = "## State\nstate: scaffolded\nbranch: test\n\n## Queue\n(empty)\n"
        write_plan(plan, content)
        assert plan.read_text() == content

    def test_rejects_content_without_state_section(self, tmp_path):
        from plan_io import write_plan
        plan = tmp_path / ".plan"
        with pytest.raises(ValueError, match="missing ## State"):
            write_plan(plan, "# Bad Plan\nno state section\n")

    def test_atomic_write(self, tmp_path):
        from plan_io import write_plan
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: old\n")
        write_plan(plan, "## State\nstate: new\n")
        assert "state: new" in plan.read_text()
        assert not (tmp_path / ".plan.tmp").exists()
