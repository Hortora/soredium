"""Tests for check-execute-verify postcondition support in orchestrator_engine.run_loop."""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


@dataclass
class FakeEngineCtx:
    workspace: Path
    project: Path
    branch: str = "test"
    base_branch: str = "main"
    on_main: bool = False
    in_slot: bool = False
    covers: str = ""
    issue_repo: str = ""
    progress: dict = field(default_factory=dict)
    dry_run: bool = False
    call_log: list = field(default_factory=list)
    plan_path: Path | None = None
    slot_path: Path | None = None
    family_root: Path | None = None
    slot_num: str = ""
    last_output: dict = field(default_factory=dict)
    steps_executed: list = field(default_factory=list)

    def done(self, step: str) -> bool:
        return self.progress.get(step) in ("done", "skipped", "skipped_error")


class TestPostconditionSkip:
    """When postcondition is already met before execution, step is skipped."""

    def test_skips_when_postcondition_met(self, tmp_path):
        from orchestrator_engine import run_loop
        from shared_steps import StepDef

        script_called = []

        def fake_script(ctx):
            script_called.append(True)
            return ["echo", "should not run"]

        step = StepDef(
            name="test_step", phase="test", step_type="mechanical",
            script_fn=fake_script,
            postcondition_fn=lambda ctx: True,
        )

        ctx = FakeEngineCtx(workspace=tmp_path, project=tmp_path)
        result = run_loop([step], ctx)

        assert result["ACTION"] == "complete"
        assert len(script_called) == 0
        assert any("postcondition_skip" in s for s in ctx.steps_executed)

    def test_marks_step_done_on_postcondition_skip(self, tmp_path):
        from orchestrator_engine import run_loop
        from shared_steps import StepDef
        from close_progress import read_close_progress

        step = StepDef(
            name="test_step", phase="test", step_type="mechanical",
            postcondition_fn=lambda ctx: True,
        )

        ctx = FakeEngineCtx(workspace=tmp_path, project=tmp_path)
        run_loop([step], ctx)

        progress = read_close_progress(tmp_path)
        assert progress.get("test_step") == "done"


class TestPostconditionVerify:
    """When postcondition fails after execution, step returns error."""

    def test_fails_when_postcondition_not_met_after_execute(self, tmp_path):
        from orchestrator_engine import run_loop
        from shared_steps import StepDef

        step = StepDef(
            name="test_step", phase="test", step_type="mechanical",
            postcondition_fn=lambda ctx: False,
        )

        ctx = FakeEngineCtx(workspace=tmp_path, project=tmp_path)

        def mock_execute(step, ctx):
            return {}

        result = run_loop([step], ctx, execute_mechanical_fn=mock_execute)
        assert result.get("ERROR") == "postcondition_failed"
        assert result.get("STEP") == "test_step"

    def test_postcondition_failure_increments_attempt(self, tmp_path):
        from orchestrator_engine import run_loop
        from shared_steps import StepDef
        from close_progress import read_close_progress

        step = StepDef(
            name="test_step", phase="test", step_type="mechanical",
            postcondition_fn=lambda ctx: False,
        )

        ctx = FakeEngineCtx(workspace=tmp_path, project=tmp_path)

        def mock_execute(step, ctx):
            return {}

        run_loop([step], ctx, execute_mechanical_fn=mock_execute)

        progress = read_close_progress(tmp_path)
        assert progress.get("test_step_mechanical_attempt") == "1"

    def test_postcondition_failure_skips_after_max_retries(self, tmp_path):
        from orchestrator_engine import run_loop
        from shared_steps import StepDef, MAX_MECHANICAL_RETRIES
        from close_progress import write_close_progress

        step = StepDef(
            name="test_step", phase="test", step_type="mechanical",
            postcondition_fn=lambda ctx: False,
        )

        write_close_progress(tmp_path,
                             {"test_step_mechanical_attempt": str(MAX_MECHANICAL_RETRIES)})

        ctx = FakeEngineCtx(
            workspace=tmp_path, project=tmp_path,
            progress={"test_step_mechanical_attempt": str(MAX_MECHANICAL_RETRIES)},
        )

        def mock_execute(step, ctx):
            return {}

        result = run_loop([step], ctx, execute_mechanical_fn=mock_execute)
        assert result["ACTION"] == "complete"
        assert any("POSTCONDITION_FAIL:skipped" in s for s in ctx.steps_executed)


class TestPostconditionNone:
    """Steps without postcondition_fn behave as before."""

    def test_no_postcondition_normal_flow(self, tmp_path):
        from orchestrator_engine import run_loop
        from shared_steps import StepDef

        step = StepDef(
            name="test_step", phase="test", step_type="mechanical",
            postcondition_fn=None,
        )

        ctx = FakeEngineCtx(workspace=tmp_path, project=tmp_path)

        def mock_execute(step, ctx):
            return {}

        result = run_loop([step], ctx, execute_mechanical_fn=mock_execute)
        assert result["ACTION"] == "complete"

    def test_no_postcondition_step_marked_done(self, tmp_path):
        from orchestrator_engine import run_loop
        from shared_steps import StepDef
        from close_progress import read_close_progress

        step = StepDef(
            name="test_step", phase="test", step_type="mechanical",
            postcondition_fn=None,
        )

        ctx = FakeEngineCtx(workspace=tmp_path, project=tmp_path)

        def mock_execute(step, ctx):
            return {}

        run_loop([step], ctx, execute_mechanical_fn=mock_execute)
        progress = read_close_progress(tmp_path)
        assert progress.get("test_step") == "done"


class TestPostconditionWithExecution:
    """Postcondition checked AFTER execution when not initially met."""

    def test_executes_then_verifies_postcondition(self, tmp_path):
        from orchestrator_engine import run_loop
        from shared_steps import StepDef

        call_order = []
        postcondition_calls = [0]

        def postcondition(ctx):
            postcondition_calls[0] += 1
            return postcondition_calls[0] > 1

        step = StepDef(
            name="test_step", phase="test", step_type="mechanical",
            postcondition_fn=postcondition,
        )

        ctx = FakeEngineCtx(workspace=tmp_path, project=tmp_path)

        def mock_execute(step, ctx):
            call_order.append("execute")
            return {}

        result = run_loop([step], ctx, execute_mechanical_fn=mock_execute)
        assert result["ACTION"] == "complete"
        assert "execute" in call_order
        assert postcondition_calls[0] == 2
