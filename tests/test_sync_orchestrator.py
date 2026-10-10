"""Tests for sync mode in the work-end orchestrator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from work_end_orchestrator import (
    OrchestratorContext,
    STEPS,
    SYNC_ONLY,
    TERMINAL,
    NOT_SYNC,
)
from shared_steps import PipelineMode


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

    def test_sync_pass_only_in_sync_mode(self):
        step = next(s for s in STEPS if s.name == "sync_pass")
        assert step.modes == SYNC_ONLY

    def test_sync_pass_excluded_from_end_mode(self):
        step = next(s for s in STEPS if s.name == "sync_pass")
        assert PipelineMode.BRANCH not in step.modes
        assert PipelineMode.SLOT not in step.modes
        assert PipelineMode.MAIN not in step.modes


class TestSyncModeExcludesTerminalSteps:
    """In sync mode, terminal steps are excluded via modes (not skip_fn)."""

    TERMINAL_STEPS = [
        "stamp_pass", "archive_slot", "report_archive",
        "checkout_main", "cleanup_stack", "cleanup",
        "cleanup_pass", "cleanup_main",
    ]

    def test_terminal_steps_exclude_sync(self):
        for step_name in self.TERMINAL_STEPS:
            step = next((s for s in STEPS if s.name == step_name), None)
            if step:
                assert PipelineMode.SYNC not in step.modes, (
                    f"Step '{step_name}' should exclude SYNC mode"
                )


class TestSyncModeExcludesSessionEndSteps:
    """In sync mode, session-end judgment steps are excluded via modes."""

    SESSION_END_STEPS = [
        "arc42_scan", "session_rename", "garden_feedback", "notes",
        "report_scaffold",
    ]

    def test_session_end_steps_exclude_sync(self):
        for step_name in self.SESSION_END_STEPS:
            step = next((s for s in STEPS if s.name == step_name), None)
            if step:
                assert PipelineMode.SYNC not in step.modes, (
                    f"Step '{step_name}' should exclude SYNC mode"
                )


class TestEndModeUnchanged:
    """End mode behavior must not change."""

    def test_stamp_pass_includes_terminal_modes(self):
        step = next(s for s in STEPS if s.name == "stamp_pass")
        assert step.modes == TERMINAL
        assert PipelineMode.BRANCH in step.modes
        assert PipelineMode.SLOT in step.modes
        assert PipelineMode.MAIN in step.modes
