"""Tests for orchestrator_engine.py three-way dispatch with outcome_fn."""
import sys
from pathlib import Path

import pytest

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from verification.outcomes import VerifyResult, Verification
from shared_steps import StepDef
from judgment import StepType
from progress import Progress
from orchestrator_engine import run_loop


def _make_ctx(workspace):
    from shared_steps import OrchestratorContextBase
    ctx = OrchestratorContextBase(
        workspace=workspace,
        project=workspace,
        branch="test-branch",
        base_branch="main",
        on_main=False,
        in_slot=False,
        covers="",
        issue_repo="",
        progress=Progress.load(workspace),
    )
    return ctx


class TestOutcomeFnPreCheck:
    def test_pass_skips_step(self, tmp_path):
        (tmp_path / ".work-progress").write_text("")
        v = Verification("test_check", VerifyResult.PASS, {"ok": True}, "repo")
        step = StepDef("my_step", "phase", StepType.MECHANICAL,
                       outcome_fn=lambda ctx: v,
                       script_fn=lambda ctx: {})
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx)
        assert "my_step:verify_skip" in ctx.steps_executed
        assert result.get("ACTION") == "complete"

    def test_fail_proceeds_to_execution(self, tmp_path):
        (tmp_path / ".work-progress").write_text("")
        call_count = 0

        def counting_outcome(ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Verification("check", VerifyResult.FAIL, {}, "r")
            return Verification("check", VerifyResult.PASS, {}, "r")

        step = StepDef("my_step", "phase", StepType.MECHANICAL,
                       outcome_fn=counting_outcome)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert result.get("ACTION") == "complete"
        assert "my_step" in ctx.steps_executed

    def test_unknown_escalates_after_max_retries(self, tmp_path):
        (tmp_path / ".work-progress").write_text(
            "my_step_mechanical_attempt=2\n_exec_ok:my_step=yes\n")
        v = Verification("check", VerifyResult.UNKNOWN,
                         {"reason": "missing"}, "repo")
        step = StepDef("my_step", "phase", StepType.MECHANICAL,
                       outcome_fn=lambda ctx: v,
                       script_fn=lambda ctx: {})
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx)
        assert result["ACTION"] == "user_input"
        assert result["CONTEXT"] == "unknown_verification"
        assert result["CHECK"] == "check"

    def test_unknown_non_idempotent_first_attempt_executes(self, tmp_path):
        (tmp_path / ".work-progress").write_text("")
        call_count = 0

        def outcome_first_unknown_then_pass(ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Verification("check", VerifyResult.UNKNOWN,
                                    {"reason": "no_sha_yet"}, "repo")
            return Verification("check", VerifyResult.PASS, {}, "repo")

        step = StepDef("my_step", "phase", StepType.MECHANICAL,
                       outcome_fn=outcome_first_unknown_then_pass,
                       idempotent=False)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert result.get("ACTION") == "complete"
        assert "my_step" in ctx.steps_executed

    def test_unknown_non_idempotent_retry_yields_when_exec_ok(self, tmp_path):
        """When a non-idempotent step previously executed OK but verification
        returned UNKNOWN, block re-execution and yield an error."""
        (tmp_path / ".work-progress").write_text(
            "my_step_mechanical_attempt=1\n_exec_ok:my_step=yes\n")
        v = Verification("check", VerifyResult.UNKNOWN,
                         {"reason": "propagating"}, "repo")
        executed = []
        step = StepDef("my_step", "phase", StepType.MECHANICAL,
                       outcome_fn=lambda ctx: v,
                       script_fn=lambda ctx: executed.append(1) or {},
                       idempotent=False)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx)
        assert result["ACTION"] == "error"
        assert result["ERROR"] == "unknown_verification"
        assert len(executed) == 0

    def test_unknown_non_idempotent_retry_executes_when_no_prior_exec(self, tmp_path):
        """When a non-idempotent step failed on execution (not verification),
        the pre-check UNKNOWN should NOT block re-execution (#468)."""
        (tmp_path / ".work-progress").write_text(
            "my_step_mechanical_attempt=1\n")
        call_count = 0

        def outcome_unknown_then_pass(ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Verification("check", VerifyResult.UNKNOWN,
                                    {"reason": "no_landed_sha"}, "repo")
            return Verification("check", VerifyResult.PASS, {}, "repo")

        step = StepDef("my_step", "phase", StepType.MECHANICAL,
                       outcome_fn=outcome_unknown_then_pass,
                       idempotent=False)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert result.get("ACTION") == "complete"
        assert "my_step" in ctx.steps_executed


class TestOutcomeFnPostCheck:
    def test_post_execution_fail_returns_error(self, tmp_path):
        (tmp_path / ".work-progress").write_text("")
        v_fail = Verification("check", VerifyResult.FAIL,
                              {"diff": ["a.py"]}, "repo")
        step = StepDef("my_step", "phase", StepType.MECHANICAL,
                       outcome_fn=lambda ctx: v_fail)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert result["ACTION"] == "error"
        assert result["ERROR"] == "verify_failed"

    def test_post_execution_unknown_retries(self, tmp_path):
        (tmp_path / ".work-progress").write_text("")
        call_count = 0

        def flaky_outcome(ctx):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return Verification("check", VerifyResult.FAIL, {}, "r")
            return Verification("check", VerifyResult.UNKNOWN, {"reason": "flaky"}, "r")

        step = StepDef("my_step", "phase", StepType.MECHANICAL,
                       outcome_fn=flaky_outcome)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert result["ACTION"] == "error"


class TestOutcomeFnOnly:
    def test_step_without_outcome_fn_executes_directly(self, tmp_path):
        (tmp_path / ".work-progress").write_text("")
        step = StepDef("my_step", "phase", StepType.MECHANICAL)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert "my_step" in ctx.steps_executed
        assert result.get("ACTION") == "complete"


class TestExecOkMarker:
    def test_exec_ok_set_after_successful_execution(self, tmp_path):
        """_exec_ok:{step} is written to progress after successful execution."""
        (tmp_path / ".work-progress").write_text("")
        step = StepDef("my_step", "phase", StepType.MECHANICAL)
        ctx = _make_ctx(tmp_path)
        run_loop([step], ctx,
                 execute_mechanical_fn=lambda s, c: {})
        assert ctx.progress.get("_exec_ok:my_step") == "yes"

    def test_exec_ok_not_set_on_error(self, tmp_path):
        """_exec_ok:{step} is NOT written when execution errors."""
        (tmp_path / ".work-progress").write_text("")
        step = StepDef("my_step", "phase", StepType.MECHANICAL)
        ctx = _make_ctx(tmp_path)
        run_loop([step], ctx,
                 execute_mechanical_fn=lambda s, c: {"ERROR": "BOOM"})
        assert ctx.progress.get("_exec_ok:my_step") != "yes"

    def test_exec_ok_persists_to_file(self, tmp_path):
        """_exec_ok:{step} is persisted to .work-progress file."""
        (tmp_path / ".work-progress").write_text("")
        step = StepDef("my_step", "phase", StepType.MECHANICAL)
        ctx = _make_ctx(tmp_path)
        run_loop([step], ctx,
                 execute_mechanical_fn=lambda s, c: {})
        reloaded = Progress.load(tmp_path)
        assert reloaded.get("_exec_ok:my_step") == "yes"
