"""Tests for work-end/shared_steps.py"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

from shared_steps import (
    StepDef,
    _is_sweep_deselected,
    sweep_defaults,
    get_sweep_selected,
    make_forage_step,
    make_garden_feedback_step,
    SWEEP_STEPS,
    WRAP_SWEEP_STEPS,
)


class FakeCtx:
    def __init__(self, progress=None):
        self.progress = progress or {}


class TestSweepDeselected:
    def test_selected_item_not_deselected(self):
        ctx = FakeCtx({"sweep_selected": "forage,protocol"})
        check = _is_sweep_deselected("forage")
        assert check(ctx) is False

    def test_unselected_item_is_deselected(self):
        ctx = FakeCtx({"sweep_selected": "forage,protocol"})
        check = _is_sweep_deselected("write_content")
        assert check(ctx) is True

    def test_empty_selected_means_nothing_deselected(self):
        ctx = FakeCtx({"sweep_selected": ""})
        check = _is_sweep_deselected("forage")
        assert check(ctx) is False

    def test_custom_key(self):
        ctx = FakeCtx({"wrap_sweep_selected": "forage"})
        check = _is_sweep_deselected("protocol", "wrap_sweep_selected")
        assert check(ctx) is True


class TestSweepDefaults:
    def test_default_items(self):
        result = sweep_defaults()
        assert "forage:on" in result
        assert "write_content:on" in result

    def test_wrap_items(self):
        result = sweep_defaults(WRAP_SWEEP_STEPS)
        assert "forage:on" in result
        assert "write_content:on" in result
        assert "impl_doc_sync" not in result
        assert "adr" not in result


class TestGetSweepSelected:
    def test_parses_csv(self):
        result = get_sweep_selected({"sweep_selected": "forage,protocol"})
        assert result == {"forage", "protocol"}

    def test_empty_returns_empty(self):
        result = get_sweep_selected({})
        assert result == set()


class TestMakeSteps:
    def test_forage_step_has_correct_phase(self):
        step = make_forage_step("wrapping", "wrap_sweep_selected")
        assert step.name == "forage"
        assert step.phase == "wrapping"
        assert step.step_type == "judgment"

    def test_garden_feedback_step(self):
        step = make_garden_feedback_step("wrapping")
        assert step.name == "garden_feedback"
        assert step.action_context_fn is not None


class TestWriteContentDiaryDetection:
    def test_finds_existing_diary_by_branch(self, tmp_path):
        from shared_steps import _find_existing_diary, OrchestratorContextBase
        blog = tmp_path / "blog"
        blog.mkdir()
        entry = blog / "2026-08-26-test-entry.md"
        entry.write_text("---\ntitle: test\nseries: issue-42-feature\n---\n# Test\n")
        ctx = OrchestratorContextBase(
            workspace=tmp_path, project=tmp_path,
            branch="issue-42-feature", base_branch="main",
            on_main=False, in_slot=False, covers="", issue_repo="",
            progress={},
        )
        result = _find_existing_diary(ctx)
        assert result["DIARY_MODE"] == "revise"
        assert str(entry) in result["EXISTING_DIARY"]

    def test_returns_new_when_no_match(self, tmp_path):
        from shared_steps import _find_existing_diary, OrchestratorContextBase
        blog = tmp_path / "blog"
        blog.mkdir()
        entry = blog / "2026-08-26-other.md"
        entry.write_text("---\ntitle: other\nseries: different-branch\n---\n")
        ctx = OrchestratorContextBase(
            workspace=tmp_path, project=tmp_path,
            branch="issue-42-feature", base_branch="main",
            on_main=False, in_slot=False, covers="", issue_repo="",
            progress={},
        )
        result = _find_existing_diary(ctx)
        assert result["DIARY_MODE"] == "new"

    def test_returns_new_when_no_blog_dir(self, tmp_path):
        from shared_steps import _find_existing_diary, OrchestratorContextBase
        ctx = OrchestratorContextBase(
            workspace=tmp_path, project=tmp_path,
            branch="issue-42-feature", base_branch="main",
            on_main=False, in_slot=False, covers="", issue_repo="",
            progress={},
        )
        result = _find_existing_diary(ctx)
        assert result.get("DIARY_MODE", "new") == "new"
