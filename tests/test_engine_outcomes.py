"""Tests for orchestrator_engine.py three-way dispatch with outcome_fn."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from verification.outcomes import VerifyResult, Verification
from shared_steps import StepDef
from orchestrator_engine import run_loop


def _make_ctx(workspace):
    ctx = MagicMock()
    ctx.workspace = workspace
    ctx.pipeline_mode = None
    ctx.progress = MagicMock()
    ctx.progress.is_done.return_value = False
    ctx.progress.is_per_repo_done.return_value = False
    ctx.progress.get.return_value = "0"
    ctx.progress.get_attempt.return_value = 0
    ctx.progress.__contains__ = lambda self, k: False
    ctx.done.return_value = False
    ctx.steps_executed = []
    ctx.last_output = {}
    ctx.repos = []
    ctx.dry_run = False
    ctx.call_log = []
    return ctx


class TestOutcomeFnPreCheck:
    def test_pass_skips_step(self, tmp_path):
        (tmp_path / ".close-progress").write_text("")
        v = Verification("test_check", VerifyResult.PASS, {"ok": True}, "repo")
        step = StepDef("my_step", "phase", "mechanical",
                       outcome_fn=lambda ctx: v,
                       script_fn=lambda ctx: {})
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx)
        assert "my_step:verify_skip" in ctx.steps_executed
        assert result.get("ACTION") == "complete"

    def test_fail_proceeds_to_execution(self, tmp_path):
        (tmp_path / ".close-progress").write_text("")
        call_count = 0

        def counting_outcome(ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Verification("check", VerifyResult.FAIL, {}, "r")
            return Verification("check", VerifyResult.PASS, {}, "r")

        step = StepDef("my_step", "phase", "mechanical",
                       outcome_fn=counting_outcome)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert result.get("ACTION") == "complete"
        assert "my_step" in ctx.steps_executed

    def test_unknown_escalates_after_max_retries(self, tmp_path):
        (tmp_path / ".close-progress").write_text("")
        v = Verification("check", VerifyResult.UNKNOWN,
                         {"reason": "missing"}, "repo")
        step = StepDef("my_step", "phase", "mechanical",
                       outcome_fn=lambda ctx: v,
                       script_fn=lambda ctx: {})
        ctx = _make_ctx(tmp_path)
        ctx.progress.get.return_value = "2"
        result = run_loop([step], ctx)
        assert result["ACTION"] == "user_input"
        assert result["CONTEXT"] == "unknown_verification"
        assert result["CHECK"] == "check"

    def test_unknown_non_idempotent_first_attempt_executes(self, tmp_path):
        (tmp_path / ".close-progress").write_text("")
        call_count = 0

        def outcome_first_unknown_then_pass(ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Verification("check", VerifyResult.UNKNOWN,
                                    {"reason": "no_sha_yet"}, "repo")
            return Verification("check", VerifyResult.PASS, {}, "repo")

        step = StepDef("my_step", "phase", "mechanical",
                       outcome_fn=outcome_first_unknown_then_pass,
                       idempotent=False)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert result.get("ACTION") == "complete"
        assert "my_step" in ctx.steps_executed

    def test_unknown_non_idempotent_retry_yields_without_execution(self, tmp_path):
        (tmp_path / ".close-progress").write_text("")
        v = Verification("check", VerifyResult.UNKNOWN,
                         {"reason": "propagating"}, "repo")
        executed = []
        step = StepDef("my_step", "phase", "mechanical",
                       outcome_fn=lambda ctx: v,
                       script_fn=lambda ctx: executed.append(1) or {},
                       idempotent=False)
        ctx = _make_ctx(tmp_path)
        ctx.progress.get.return_value = "1"
        result = run_loop([step], ctx)
        assert result["ACTION"] == "error"
        assert result["ERROR"] == "unknown_verification"
        assert len(executed) == 0


class TestOutcomeFnPostCheck:
    def test_post_execution_fail_returns_error(self, tmp_path):
        (tmp_path / ".close-progress").write_text("")
        v_fail = Verification("check", VerifyResult.FAIL,
                              {"diff": ["a.py"]}, "repo")
        step = StepDef("my_step", "phase", "mechanical",
                       outcome_fn=lambda ctx: v_fail)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert result["ACTION"] == "error"
        assert result["ERROR"] == "verify_failed"

    def test_post_execution_unknown_retries(self, tmp_path):
        (tmp_path / ".close-progress").write_text("")
        call_count = 0

        def flaky_outcome(ctx):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return Verification("check", VerifyResult.FAIL, {}, "r")
            return Verification("check", VerifyResult.UNKNOWN, {"reason": "flaky"}, "r")

        step = StepDef("my_step", "phase", "mechanical",
                       outcome_fn=flaky_outcome)
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert result["ACTION"] == "error"


class TestOutcomeFnOnly:
    def test_step_without_outcome_fn_executes_directly(self, tmp_path):
        (tmp_path / ".close-progress").write_text("")
        step = StepDef("my_step", "phase", "mechanical")
        ctx = _make_ctx(tmp_path)
        result = run_loop([step], ctx,
                          execute_mechanical_fn=lambda s, c: {})
        assert "my_step" in ctx.steps_executed
        assert result.get("ACTION") == "complete"
