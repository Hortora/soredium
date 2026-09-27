"""Tests for sync mode in the work-end orchestrator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from work_end_orchestrator import (
    OrchestratorContext,
    STEPS,
    _skip_sync_mode,
    _skip_not_sync_mode,
)


def _make_ctx(mode: str = "end", **overrides) -> OrchestratorContext:
    defaults = dict(
        workspace=Path("/tmp/ws"),
        project=Path("/tmp/proj"),
        branch="test-branch",
        base_branch="main",
        meta_state="closing:stamped",
        on_main=False,
        in_slot=False,
        covers="1",
        issue_repo="test/repo",
        progress={},
        mode=mode,
    )
    defaults.update(overrides)
    return OrchestratorContext(**defaults)


class TestSyncSkipPredicates:
    def test_skip_sync_mode_true_when_sync(self):
        ctx = _make_ctx(mode="sync")
        assert _skip_sync_mode(ctx) is True

    def test_skip_sync_mode_false_when_end(self):
        ctx = _make_ctx(mode="end")
        assert _skip_sync_mode(ctx) is False

    def test_skip_not_sync_mode_true_when_end(self):
        ctx = _make_ctx(mode="end")
        assert _skip_not_sync_mode(ctx) is True

    def test_skip_not_sync_mode_false_when_sync(self):
        ctx = _make_ctx(mode="sync")
        assert _skip_not_sync_mode(ctx) is False


class TestSyncPassStepExists:
    def test_sync_pass_step_in_steps(self):
        step_names = [s.name for s in STEPS]
        assert "sync_pass" in step_names

    def test_sync_pass_is_lifecycle_step(self):
        step = next(s for s in STEPS if s.name == "sync_pass")
        assert step.step_type == "lifecycle"
        assert step.from_state == "closing:stamped"
        assert step.to_state == "active"
        assert step.event == "sync_pass"

    def test_sync_pass_skipped_when_not_sync(self):
        step = next(s for s in STEPS if s.name == "sync_pass")
        ctx = _make_ctx(mode="end")
        assert step.skip_fn(ctx) is True

    def test_sync_pass_not_skipped_when_sync(self):
        step = next(s for s in STEPS if s.name == "sync_pass")
        ctx = _make_ctx(mode="sync")
        assert step.skip_fn(ctx) is False


class TestSyncModeSkipsTerminalSteps:
    """In sync mode, stamp/archive/checkout/cleanup steps are skipped."""

    TERMINAL_STEPS = [
        "stamp_pass", "archive_slot", "report_archive",
        "checkout_main", "cleanup_stack", "cleanup",
        "cleanup_pass", "cleanup_main",
    ]

    def test_terminal_steps_skipped_in_sync(self):
        ctx = _make_ctx(mode="sync")
        for step_name in self.TERMINAL_STEPS:
            step = next((s for s in STEPS if s.name == step_name), None)
            if step and step.skip_fn:
                assert step.skip_fn(ctx) is True, (
                    f"Step '{step_name}' should be skipped in sync mode"
                )


class TestSyncModeSkipsSessionEndSteps:
    """In sync mode, session-end judgment steps are skipped."""

    SESSION_END_STEPS = [
        "arc42_scan", "session_rename", "garden_feedback", "notes",
        "report_scaffold",
    ]

    def test_session_end_steps_skipped_in_sync(self):
        ctx = _make_ctx(mode="sync")
        for step_name in self.SESSION_END_STEPS:
            step = next((s for s in STEPS if s.name == step_name), None)
            if step and step.skip_fn:
                assert step.skip_fn(ctx) is True, (
                    f"Step '{step_name}' should be skipped in sync mode"
                )


class TestEndModeUnchanged:
    """End mode behavior must not change."""

    def test_stamp_pass_not_skipped_in_end_mode_no_cycle(self):
        ctx = _make_ctx(mode="end")
        step = next(s for s in STEPS if s.name == "stamp_pass")
        # _skip_cycle_mode checks .plan which doesn't exist here → returns False
        assert step.skip_fn(ctx) is False

    def test_sync_pass_skipped_in_end_mode(self):
        ctx = _make_ctx(mode="end")
        step = next(s for s in STEPS if s.name == "sync_pass")
        assert step.skip_fn(ctx) is True
