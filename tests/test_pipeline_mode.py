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


class TestEngineRequiresValidation:
    """Test that the engine validates requires references at startup."""

    def test_invalid_requires_reference_raises(self):
        from orchestrator_engine import validate_requires
        steps = [
            StepDef("step_a", "test", "mechanical"),
            StepDef("step_b", "test", "mechanical", requires=("nonexistent",)),
        ]
        with pytest.raises(ValueError, match="nonexistent"):
            validate_requires(steps)

    def test_valid_requires_passes(self):
        from orchestrator_engine import validate_requires
        steps = [
            StepDef("step_a", "test", "mechanical"),
            StepDef("step_b", "test", "mechanical", requires=("step_a",)),
        ]
        validate_requires(steps)

    def test_empty_requires_passes(self):
        from orchestrator_engine import validate_requires
        steps = [
            StepDef("step_a", "test", "mechanical"),
            StepDef("step_b", "test", "mechanical"),
        ]
        validate_requires(steps)

    def test_self_reference_raises(self):
        from orchestrator_engine import validate_requires
        steps = [
            StepDef("step_a", "test", "mechanical", requires=("step_a",)),
        ]
        with pytest.raises(ValueError, match="step_a"):
            validate_requires(steps)


class TestStepsRequiresIntegrity:
    """Test that the actual STEPS list passes validation."""

    def test_steps_requires_all_resolve(self):
        from work_end_orchestrator import STEPS
        from orchestrator_engine import validate_requires
        validate_requires(STEPS)

    def test_close_issues_requires_verify(self):
        from work_end_orchestrator import STEPS
        step = next(s for s in STEPS if s.name == "close_issues")
        assert "verify" in step.requires

    def test_land_requires_squash(self):
        from work_end_orchestrator import STEPS
        step = next(s for s in STEPS if s.name == "land")
        assert "squash" in step.requires

    def test_squash_requires_rebase(self):
        from work_end_orchestrator import STEPS
        step = next(s for s in STEPS if s.name == "squash")
        assert "rebase" in step.requires


class TestEngineRequiresRuntime:
    """Test that the engine checks required steps before execution."""

    def test_step_with_unmet_requirement_skips(self):
        from orchestrator_engine import run_loop
        from shared_steps import OrchestratorContextBase
        from work_progress import delete_progress

        workspace = Path("/tmp/test_requires_runtime")
        workspace.mkdir(exist_ok=True)
        delete_progress(workspace)

        step_a = StepDef("step_a", "test", "mechanical", script_fn=lambda ctx: None)
        step_b = StepDef("step_b", "test", "mechanical",
                         requires=("step_a",), script_fn=lambda ctx: None)

        class FakeCtx(OrchestratorContextBase):
            def done(self, step):
                return self.progress.get(step) in ("done", "skipped", "skipped_error")

        ctx = FakeCtx(
            workspace=workspace, project=workspace,
            branch="test", base_branch="main",
            on_main=False, in_slot=False,
            covers="", issue_repo="",
            progress={},
        )

        result = run_loop([step_a, step_b], ctx)
        assert result["ACTION"] == "complete"
        assert "step_a" in ctx.steps_executed
        assert "step_b" in ctx.steps_executed

        delete_progress(workspace)

    def test_step_runs_when_requirement_met(self):
        from orchestrator_engine import run_loop
        from shared_steps import OrchestratorContextBase
        from work_progress import delete_progress, update_progress

        workspace = Path("/tmp/test_requires_met")
        workspace.mkdir(exist_ok=True)
        delete_progress(workspace)
        update_progress(workspace, "step_a", "done")

        step_b = StepDef("step_b", "test", "mechanical",
                         requires=("step_a",), script_fn=lambda ctx: None)

        class FakeCtx(OrchestratorContextBase):
            def done(self, step):
                return self.progress.get(step) in ("done", "skipped", "skipped_error")

        ctx = FakeCtx(
            workspace=workspace, project=workspace,
            branch="test", base_branch="main",
            on_main=False, in_slot=False,
            covers="", issue_repo="",
            progress={"step_a": "done"},
        )

        result = run_loop([step_b], ctx)
        assert result["ACTION"] == "complete"
        assert "step_b" in ctx.steps_executed

        delete_progress(workspace)

    def test_step_with_unmet_requirement_errors(self):
        """A step whose active requires are not met produces an error."""
        from orchestrator_engine import run_loop
        from shared_steps import OrchestratorContextBase
        from work_progress import delete_progress

        workspace = Path("/tmp/test_requires_unmet")
        workspace.mkdir(exist_ok=True)
        delete_progress(workspace)

        step_b = StepDef("step_b", "test", "mechanical",
                         requires=("step_a",), script_fn=lambda ctx: None)
        step_a = StepDef("step_a", "test", "judgment")

        class FakeCtx(OrchestratorContextBase):
            def done(self, step):
                return self.progress.get(step) in ("done", "skipped", "skipped_error")

        ctx = FakeCtx(
            workspace=workspace, project=workspace,
            branch="test", base_branch="main",
            on_main=False, in_slot=False,
            covers="", issue_repo="",
            progress={},
        )

        result = run_loop([step_b, step_a], ctx)
        assert result["ACTION"] == "error"
        assert "step_a" in result.get("REASON", "")

        delete_progress(workspace)

    def test_excluded_dependency_is_satisfied(self):
        """If a required step is not in the step list, dependency is satisfied."""
        from orchestrator_engine import run_loop
        from shared_steps import OrchestratorContextBase
        from work_progress import delete_progress

        workspace = Path("/tmp/test_requires_excluded")
        workspace.mkdir(exist_ok=True)
        delete_progress(workspace)

        step_b = StepDef("step_b", "test", "mechanical",
                         requires=("step_a",), script_fn=lambda ctx: None)

        class FakeCtx(OrchestratorContextBase):
            def done(self, step):
                return self.progress.get(step) in ("done", "skipped", "skipped_error")

        ctx = FakeCtx(
            workspace=workspace, project=workspace,
            branch="test", base_branch="main",
            on_main=False, in_slot=False,
            covers="", issue_repo="",
            progress={},
        )

        result = run_loop([step_b], ctx)
        assert result["ACTION"] == "complete"

        delete_progress(workspace)


    def test_per_repo_done_satisfies_requires(self):
        """Per-repo progress keys (step:repo) satisfy the requires check."""
        from orchestrator_engine import run_loop
        from shared_steps import OrchestratorContextBase
        from work_progress import delete_progress, update_progress

        workspace = Path("/tmp/test_requires_per_repo")
        workspace.mkdir(exist_ok=True)
        delete_progress(workspace)
        update_progress(workspace, "rebase:engine", "done")
        update_progress(workspace, "rebase:soredium", "done")

        land_step = StepDef("land", "test", "mechanical",
                            requires=("rebase",), script_fn=lambda ctx: None)
        rebase_step = StepDef("rebase", "test", "mechanical",
                              script_fn=lambda ctx: None)

        class FakeCtx(OrchestratorContextBase):
            def done(self, step):
                return self.progress.get(step) in ("done", "skipped", "skipped_error")

        ctx = FakeCtx(
            workspace=workspace, project=workspace,
            branch="test", base_branch="main",
            on_main=False, in_slot=False,
            covers="", issue_repo="",
            progress={"rebase:engine": "done", "rebase:soredium": "done"},
        )

        result = run_loop([rebase_step, land_step], ctx)
        assert result["ACTION"] == "complete"
        assert "land" in ctx.steps_executed

        delete_progress(workspace)

    def test_mode_filtered_dependency_is_satisfied(self):
        """If a required step is excluded by mode filtering, the dependency is satisfied."""
        from orchestrator_engine import run_loop
        from shared_steps import OrchestratorContextBase
        from work_progress import delete_progress

        workspace = Path("/tmp/test_requires_mode_filtered")
        workspace.mkdir(exist_ok=True)
        delete_progress(workspace)

        rebase_step = StepDef("rebase", "test", "mechanical",
                              modes=frozenset({PipelineMode.BRANCH}),
                              script_fn=lambda ctx: None)
        land_step = StepDef("land", "test", "mechanical",
                            requires=("rebase",),
                            script_fn=lambda ctx: None)

        class FakeCtx(OrchestratorContextBase):
            pipeline_mode = PipelineMode.MAIN

            def done(self, step):
                return self.progress.get(step) in ("done", "skipped", "skipped_error")

        ctx = FakeCtx(
            workspace=workspace, project=workspace,
            branch="main", base_branch="main",
            on_main=True, in_slot=False,
            covers="", issue_repo="",
            progress={},
        )

        result = run_loop([rebase_step, land_step], ctx)
        assert result["ACTION"] == "complete"
        assert "land" in ctx.steps_executed
        assert "rebase" not in ctx.steps_executed

        delete_progress(workspace)


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
