"""Tests for PipelineMode determination and engine-level mode filtering."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

from shared_steps import PipelineMode, ALL_MODES, StepDef


class TestDeterminePipelineMode:
    def test_sync_mode(self):
        from work_end_orchestrator import determine_pipeline_mode
        result = determine_pipeline_mode(
            on_main=False, in_slot=False, mode="sync",
            workspace=Path("/tmp"), covers="", issue_repo="",
        )
        assert result == PipelineMode.SYNC

    def test_main_mode(self):
        from work_end_orchestrator import determine_pipeline_mode
        result = determine_pipeline_mode(
            on_main=True, in_slot=False, mode="end",
            workspace=Path("/tmp"), covers="", issue_repo="",
        )
        assert result == PipelineMode.MAIN

    def test_slot_mode(self):
        from work_end_orchestrator import determine_pipeline_mode
        result = determine_pipeline_mode(
            on_main=False, in_slot=True, mode="end",
            workspace=Path("/tmp"), covers="", issue_repo="",
        )
        assert result == PipelineMode.SLOT

    def test_branch_mode(self):
        from work_end_orchestrator import determine_pipeline_mode
        result = determine_pipeline_mode(
            on_main=False, in_slot=False, mode="end",
            workspace=Path("/tmp"), covers="", issue_repo="",
        )
        assert result == PipelineMode.BRANCH

    def test_cycle_mode_when_plan_has_remaining(self, tmp_path):
        from work_end_orchestrator import determine_pipeline_mode
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\nbranch: test\n\n## Queue\n"
            "- [x] org/repo#1 — Done\n"
            "- [ ] org/repo#2 — Not done ← active\n"
        )
        with patch("work_end_orchestrator._all_covers_closed", return_value=False):
            result = determine_pipeline_mode(
                on_main=False, in_slot=False, mode="end",
                workspace=tmp_path, covers="1,2", issue_repo="org/repo",
            )
        assert result == PipelineMode.CYCLE

    def test_not_cycle_when_all_covers_closed(self, tmp_path):
        from work_end_orchestrator import determine_pipeline_mode
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\nbranch: test\n\n## Queue\n"
            "- [x] org/repo#1 — Done\n"
            "- [ ] org/repo#2 — Not done ← active\n"
        )
        with patch("work_end_orchestrator._all_covers_closed", return_value=True):
            result = determine_pipeline_mode(
                on_main=False, in_slot=False, mode="end",
                workspace=tmp_path, covers="1,2", issue_repo="org/repo",
            )
        assert result == PipelineMode.BRANCH

    def test_not_cycle_when_no_plan(self):
        from work_end_orchestrator import determine_pipeline_mode
        result = determine_pipeline_mode(
            on_main=False, in_slot=False, mode="end",
            workspace=Path("/nonexistent"), covers="", issue_repo="",
        )
        assert result == PipelineMode.BRANCH

    def test_sync_takes_precedence_over_slot(self):
        from work_end_orchestrator import determine_pipeline_mode
        result = determine_pipeline_mode(
            on_main=False, in_slot=True, mode="sync",
            workspace=Path("/tmp"), covers="", issue_repo="",
        )
        assert result == PipelineMode.SYNC

    def test_cycle_takes_precedence_over_slot(self, tmp_path):
        from work_end_orchestrator import determine_pipeline_mode
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\nbranch: test\n\n## Queue\n"
            "- [x] org/repo#1 — Done\n"
            "- [ ] org/repo#2 — Pending ← active\n"
        )
        with patch("work_end_orchestrator._all_covers_closed", return_value=False):
            result = determine_pipeline_mode(
                on_main=False, in_slot=True, mode="end",
                workspace=tmp_path, covers="1,2", issue_repo="org/repo",
            )
        assert result == PipelineMode.CYCLE


class TestEngineModeFiltering:
    """Test that the engine excludes steps not in the current mode."""

    def test_step_excluded_by_mode_never_executes(self):
        from orchestrator_engine import run_loop
        from shared_steps import OrchestratorContextBase
        from work_progress import update_progress, delete_progress

        workspace = Path("/tmp/test_mode_filter")
        workspace.mkdir(exist_ok=True)
        delete_progress(workspace)

        executed = []

        def script_fn(ctx):
            return None

        branch_step = StepDef(
            "branch_only", "test", "mechanical",
            modes=frozenset({PipelineMode.BRANCH}),
            script_fn=script_fn,
        )
        all_step = StepDef(
            "runs_everywhere", "test", "mechanical",
            script_fn=script_fn,
        )

        class FakeCtx(OrchestratorContextBase):
            pipeline_mode = PipelineMode.MAIN

            def done(self, step):
                return False

        ctx = FakeCtx(
            workspace=workspace, project=workspace,
            branch="test", base_branch="main",
            on_main=True, in_slot=False,
            covers="", issue_repo="",
            progress={},
        )

        result = run_loop(
            [branch_step, all_step], ctx,
        )

        assert result["ACTION"] == "complete"
        assert "branch_only" not in ctx.steps_executed
        assert "runs_everywhere" in ctx.steps_executed

        delete_progress(workspace)

    def test_all_modes_step_always_runs(self):
        from orchestrator_engine import run_loop
        from shared_steps import OrchestratorContextBase
        from work_progress import delete_progress

        workspace = Path("/tmp/test_mode_all")
        workspace.mkdir(exist_ok=True)
        delete_progress(workspace)

        step = StepDef("universal", "test", "mechanical", script_fn=lambda ctx: None)

        for mode in PipelineMode:
            class FakeCtx(OrchestratorContextBase):
                pipeline_mode = mode

                def done(self, step):
                    return False

            ctx = FakeCtx(
                workspace=workspace, project=workspace,
                branch="test", base_branch="main",
                on_main=False, in_slot=False,
                covers="", issue_repo="",
                progress={},
            )
            result = run_loop([step], ctx)
            assert result["ACTION"] == "complete", f"Failed for mode {mode}"
            delete_progress(workspace)
