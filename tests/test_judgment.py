"""Tests for typed LLM interface — JudgmentRequest/Response protocol (#451)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

from judgment import StepType


class TestStepType:
    def test_mechanical_value(self):
        from judgment import StepType
        assert StepType.MECHANICAL.value == "mechanical"

    def test_judgment_value(self):
        from judgment import StepType
        assert StepType.JUDGMENT.value == "judgment"

    def test_lifecycle_value(self):
        from judgment import StepType
        assert StepType.LIFECYCLE.value == "lifecycle"

    def test_from_string(self):
        from judgment import StepType
        assert StepType("mechanical") == StepType.MECHANICAL

    def test_invalid_raises(self):
        from judgment import StepType
        with pytest.raises(ValueError):
            StepType("invalid")


class TestOutcome:
    def test_completed_value(self):
        from judgment import Outcome
        assert Outcome.COMPLETED.value == "completed"

    def test_skipped_value(self):
        from judgment import Outcome
        assert Outcome.SKIPPED.value == "skipped"

    def test_blocked_value(self):
        from judgment import Outcome
        assert Outcome.BLOCKED.value == "blocked"

    def test_from_string(self):
        from judgment import Outcome
        assert Outcome("skipped") == Outcome.SKIPPED


class TestJudgmentRequest:
    def test_frozen_dataclass(self):
        from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA
        req = JudgmentRequest(
            step="code_review",
            handler="handlers/review.md",
            context={"DIFF_RANGE": "main..feature"},
            response_schema=DEFAULT_JUDGMENT_SCHEMA,
            skippable=True,
            timeout_hint="standard",
        )
        assert req.step == "code_review"
        assert req.handler == "handlers/review.md"
        with pytest.raises(AttributeError):
            req.step = "other"

    def test_none_handler(self):
        from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA
        req = JudgmentRequest(
            step="forage", handler=None,
            context={}, response_schema=DEFAULT_JUDGMENT_SCHEMA,
            skippable=True, timeout_hint="standard",
        )
        assert req.handler is None


class TestJudgmentResponse:
    def test_completed_response(self):
        from judgment import JudgmentResponse, Outcome
        resp = JudgmentResponse(
            step="code_review",
            outcome=Outcome.COMPLETED,
            produced=3,
            evidence={"findings": 3},
            block_reason=None,
        )
        assert resp.outcome == Outcome.COMPLETED
        assert resp.produced == 3

    def test_blocked_response(self):
        from judgment import JudgmentResponse, Outcome
        resp = JudgmentResponse(
            step="squash",
            outcome=Outcome.BLOCKED,
            produced=0,
            evidence={},
            block_reason="merge conflict",
        )
        assert resp.block_reason == "merge conflict"


class TestSerializeRequest:
    def test_round_trip_basic_fields(self):
        from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA, serialize_request
        req = JudgmentRequest(
            step="code_review",
            handler="handlers/review.md",
            context={"DIFF_RANGE": "main..feature"},
            response_schema=DEFAULT_JUDGMENT_SCHEMA,
            skippable=True,
            timeout_hint="standard",
        )
        result = serialize_request(req)
        assert result["ACTION"] == "code_review"
        assert result["HANDLER"] == "handlers/review.md"
        assert result["DIFF_RANGE"] == "main..feature"
        assert result["SKIPPABLE"] == "yes"
        assert result["TIMEOUT_HINT"] == "standard"
        assert "step_done=code_review" in result["COMPLETE_WITH"]
        assert "outcome=" in result["COMPLETE_WITH"]

    def test_none_handler_omitted(self):
        from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA, serialize_request
        req = JudgmentRequest(
            step="forage", handler=None,
            context={}, response_schema=DEFAULT_JUDGMENT_SCHEMA,
            skippable=True, timeout_hint="standard",
        )
        result = serialize_request(req)
        assert "HANDLER" not in result

    def test_schema_serialized_as_json(self):
        from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA, serialize_request
        req = JudgmentRequest(
            step="review", handler=None,
            context={}, response_schema=DEFAULT_JUDGMENT_SCHEMA,
            skippable=True, timeout_hint="standard",
        )
        result = serialize_request(req)
        parsed = json.loads(result["SCHEMA"])
        assert parsed["type"] == "object"
        assert "step" in parsed["properties"]


class TestParseResponse:
    def test_parse_completed(self):
        from judgment import parse_response, Outcome
        args = {"step_done": "code_review", "produced": "3", "outcome": "completed"}
        resp = parse_response(args)
        assert resp.step == "code_review"
        assert resp.outcome == Outcome.COMPLETED
        assert resp.produced == 3

    def test_parse_defaults_outcome_completed(self):
        from judgment import parse_response, Outcome
        args = {"step_done": "code_review", "produced": "2"}
        resp = parse_response(args)
        assert resp.outcome == Outcome.COMPLETED

    def test_parse_skipped(self):
        from judgment import parse_response, Outcome
        args = {"step_done": "forage", "outcome": "skipped"}
        resp = parse_response(args)
        assert resp.outcome == Outcome.SKIPPED
        assert resp.produced == 0

    def test_parse_blocked(self):
        from judgment import parse_response, Outcome
        args = {"step_done": "squash", "outcome": "blocked",
                "block_reason": "merge conflict"}
        resp = parse_response(args)
        assert resp.outcome == Outcome.BLOCKED
        assert resp.block_reason == "merge conflict"

    def test_parse_evidence_json(self):
        from judgment import parse_response
        args = {"step_done": "review", "produced": "1",
                "evidence": '{"findings": 1}'}
        resp = parse_response(args)
        assert resp.evidence == {"findings": 1}

    def test_parse_invalid_outcome_raises(self):
        from judgment import parse_response
        args = {"step_done": "review", "outcome": "invalid"}
        with pytest.raises(ValueError):
            parse_response(args)

    def test_parse_missing_produced_defaults_zero(self):
        from judgment import parse_response
        args = {"step_done": "forage", "outcome": "completed"}
        resp = parse_response(args)
        assert resp.produced == 0

    def test_parse_malformed_evidence_defaults_empty(self):
        from judgment import parse_response
        args = {"step_done": "review", "evidence": "not-json"}
        resp = parse_response(args)
        assert resp.evidence == {}


class TestValidateResponse:
    def test_valid_default_schema(self):
        from judgment import JudgmentResponse, Outcome, DEFAULT_JUDGMENT_SCHEMA, validate_response
        resp = JudgmentResponse("review", Outcome.COMPLETED, 0, {}, None)
        errors = validate_response(resp, DEFAULT_JUDGMENT_SCHEMA)
        assert errors == []

    def test_invalid_outcome_rejected(self):
        from judgment import validate_response, DEFAULT_JUDGMENT_SCHEMA
        resp_dict = {"step": "review", "outcome": "invalid", "produced": 0}
        errors = validate_response_dict(resp_dict, DEFAULT_JUDGMENT_SCHEMA)
        assert any("outcome" in e for e in errors)

    def test_negative_produced_rejected(self):
        from judgment import JudgmentResponse, Outcome, DEFAULT_JUDGMENT_SCHEMA, validate_response
        resp = JudgmentResponse("review", Outcome.COMPLETED, -1, {}, None)
        errors = validate_response(resp, DEFAULT_JUDGMENT_SCHEMA)
        assert any("produced" in e for e in errors)

    def test_custom_schema_validates(self):
        from judgment import JudgmentResponse, Outcome, validate_response
        schema = {
            "type": "object",
            "properties": {
                "step": {"type": "string"},
                "outcome": {"type": "string", "enum": ["completed", "skipped", "blocked"]},
                "produced": {"type": "integer", "minimum": 0},
            },
            "required": ["step", "outcome", "produced"],
        }
        resp = JudgmentResponse("squash", Outcome.COMPLETED, 1, {}, None)
        errors = validate_response(resp, schema)
        assert errors == []


class TestYieldJudgmentRequest:
    def test_emits_handler_in_output(self, tmp_path):
        from orchestrator_engine import _yield_judgment
        from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA
        from progress import Progress

        req = JudgmentRequest(
            step="code_review",
            handler="handlers/review.md",
            context={"DIFF_RANGE": "main..feature"},
            response_schema=DEFAULT_JUDGMENT_SCHEMA,
            skippable=True,
            timeout_hint="standard",
        )
        progress = Progress()
        result = _yield_judgment(req, tmp_path, progress)
        assert result["ACTION"] == "code_review"
        assert result["HANDLER"] == "handlers/review.md"
        assert result["SKIPPABLE"] == "yes"
        assert "outcome=" in result["COMPLETE_WITH"]

    def test_omits_handler_when_none(self, tmp_path):
        from orchestrator_engine import _yield_judgment
        from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA
        from progress import Progress

        req = JudgmentRequest(
            step="forage", handler=None,
            context={}, response_schema=DEFAULT_JUDGMENT_SCHEMA,
            skippable=True, timeout_hint="standard",
        )
        progress = Progress()
        result = _yield_judgment(req, tmp_path, progress)
        assert "HANDLER" not in result
        assert result["ACTION"] == "forage"

    def test_context_fields_included(self, tmp_path):
        from orchestrator_engine import _yield_judgment
        from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA
        from progress import Progress

        req = JudgmentRequest(
            step="code_review", handler=None,
            context={"DIFF_RANGE": "main..feature", "DIMENSION": "conformance"},
            response_schema=DEFAULT_JUDGMENT_SCHEMA,
            skippable=True, timeout_hint="extended",
        )
        progress = Progress()
        result = _yield_judgment(req, tmp_path, progress)
        assert result["DIFF_RANGE"] == "main..feature"
        assert result["DIMENSION"] == "conformance"
        assert result["TIMEOUT_HINT"] == "extended"

    def test_attempt_tracking_preserved(self, tmp_path):
        from orchestrator_engine import _yield_judgment
        from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA
        from progress import Progress
        from work_progress import read_progress

        req = JudgmentRequest(
            step="review", handler=None,
            context={}, response_schema=DEFAULT_JUDGMENT_SCHEMA,
            skippable=True, timeout_hint="standard",
        )
        progress = Progress()
        _yield_judgment(req, tmp_path, progress)
        disk = read_progress(tmp_path)
        assert disk.get("review_attempt") == "1"


class TestRunLoopAssemblesRequest:
    def test_judgment_step_yields_with_handler(self, tmp_path):
        from orchestrator_engine import run_loop
        from shared_steps import StepDef
        from judgment import StepType
        from progress import Progress

        step = StepDef(
            "test_step", "test", StepType.JUDGMENT,
            handler="handlers/test.md",
            action_context_fn=lambda ctx: {"KEY": "value"},
        )
        ctx_class = type("Ctx", (), {
            "workspace": tmp_path, "project": tmp_path,
            "progress": Progress(), "steps_executed": [],
            "repos": [], "last_output": {},
            "done": lambda self, s: self.progress.get(s) in ("done", "skipped", "skipped_error"),
        })
        ctx = ctx_class()
        result = run_loop([step], ctx)
        assert result["ACTION"] == "test_step"
        assert result["HANDLER"] == "handlers/test.md"
        assert result["KEY"] == "value"
        assert result["SKIPPABLE"] == "yes"


class TestResponseValidationIntegration:
    def test_invalid_outcome_returns_schema_violation(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage")
        update_close_progress(tmp_path, "_branch", "issue-test")
        update_close_progress(tmp_path, "last_yielded", "forage")
        (tmp_path / "project").mkdir(exist_ok=True)
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "step_done": "forage",
            "outcome": "invalid_value",
        })
        assert result.get("ERROR") in ("schema_violation", "invalid_outcome")

    def test_valid_outcome_accepted(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage")
        update_close_progress(tmp_path, "_branch", "issue-test")
        update_close_progress(tmp_path, "last_yielded", "forage")
        (tmp_path / "project").mkdir(exist_ok=True)
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "step_done": "forage",
            "outcome": "completed",
            "produced": "0",
        })
        assert result.get("ERROR") != "schema_violation"

    def test_skip_via_outcome_skipped(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress, read_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage")
        update_close_progress(tmp_path, "_branch", "issue-test")
        update_close_progress(tmp_path, "last_yielded", "forage")
        (tmp_path / "project").mkdir(exist_ok=True)
        run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "step_done": "forage",
            "outcome": "skipped",
        })
        progress = read_close_progress(tmp_path)
        assert progress.get("forage") == "skipped"

    def test_blocked_outcome_returns_error(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage")
        update_close_progress(tmp_path, "_branch", "issue-test")
        update_close_progress(tmp_path, "last_yielded", "forage")
        (tmp_path / "project").mkdir(exist_ok=True)
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "step_done": "forage",
            "outcome": "blocked",
            "block_reason": "garden not running",
        })
        assert result.get("ERROR") == "step_blocked"


class TestHandlerMetadata:
    def test_work_end_handlers_exist(self):
        from work_end_orchestrator import STEPS
        handler_root = Path(__file__).parent.parent / "work-end"
        for step in STEPS:
            if step.step_type == StepType.JUDGMENT and step.handler:
                path = handler_root / step.handler
                assert path.exists(), f"Handler for '{step.name}' not found: {path}"

    def test_work_handlers_exist(self):
        from work import PIPELINES
        handler_root = Path(__file__).parent.parent / "work"
        for cmd, steps in PIPELINES.items():
            for step in steps:
                if step.step_type == StepType.JUDGMENT and step.handler:
                    path = handler_root / step.handler
                    assert path.exists(), f"Handler for '{step.name}' not found: {path}"

    def test_steps_with_verify_fn_have_schema(self):
        from work_end_orchestrator import STEPS
        for step in STEPS:
            if step.step_type == StepType.JUDGMENT and step.verify_fn:
                assert step.response_schema is not None, (
                    f"Step '{step.name}' has verify_fn but no response_schema"
                )


class TestStepTypeConverted:
    """Verify all step definitions use StepType enum, not strings."""

    def test_all_work_end_steps_use_enum(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
        from work_end_orchestrator import STEPS
        from judgment import StepType
        for step in STEPS:
            assert isinstance(step.step_type, StepType), (
                f"Step '{step.name}' uses {type(step.step_type).__name__}, not StepType"
            )

    def test_all_wrap_steps_use_enum(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "handover"))
        from wrap_orchestrator import WRAP_STEPS
        from judgment import StepType
        for step in WRAP_STEPS:
            assert isinstance(step.step_type, StepType), (
                f"Step '{step.name}' uses {type(step.step_type).__name__}, not StepType"
            )

    def test_all_work_pipeline_steps_use_enum(self):
        from work import PIPELINES
        from judgment import StepType
        for cmd, steps in PIPELINES.items():
            for step in steps:
                assert isinstance(step.step_type, StepType), (
                    f"Step '{step.name}' in pipeline '{cmd}' uses "
                    f"{type(step.step_type).__name__}, not StepType"
                )


class TestDifferentiatedSchemas:
    def test_default_schema_does_not_require_produced(self):
        from judgment import JudgmentResponse, Outcome, DEFAULT_JUDGMENT_SCHEMA, validate_response
        resp = JudgmentResponse("forage", Outcome.COMPLETED, 0, {}, None)
        errors = validate_response(resp, DEFAULT_JUDGMENT_SCHEMA)
        assert errors == []

    def test_produced_required_schema_requires_produced(self):
        from judgment import PRODUCED_REQUIRED_SCHEMA
        assert "produced" in PRODUCED_REQUIRED_SCHEMA["required"]

    def test_default_schema_omits_produced_from_required(self):
        from judgment import DEFAULT_JUDGMENT_SCHEMA
        assert "produced" not in DEFAULT_JUDGMENT_SCHEMA["required"]

    def test_forcing_function_schema_requires_evidence_open_findings(self):
        from judgment import JudgmentResponse, Outcome, FORCING_FUNCTION_SCHEMA, validate_response
        resp = JudgmentResponse("forcing_function", Outcome.COMPLETED, 0, {}, None)
        errors = validate_response(resp, FORCING_FUNCTION_SCHEMA)
        assert any("open_findings" in e for e in errors)

    def test_forcing_function_schema_accepts_valid_evidence(self):
        from judgment import JudgmentResponse, Outcome, FORCING_FUNCTION_SCHEMA, validate_response
        resp = JudgmentResponse("forcing_function", Outcome.COMPLETED, 0, {"open_findings": 0}, None)
        errors = validate_response(resp, FORCING_FUNCTION_SCHEMA)
        assert errors == []

    def test_forcing_function_schema_rejects_wrong_type(self):
        from judgment import JudgmentResponse, Outcome, FORCING_FUNCTION_SCHEMA, validate_response
        resp = JudgmentResponse("forcing_function", Outcome.COMPLETED, 0, {"open_findings": "none"}, None)
        errors = validate_response(resp, FORCING_FUNCTION_SCHEMA)
        assert any("integer" in e for e in errors)

    def test_squash_schema_requires_evidence_verified(self):
        from judgment import JudgmentResponse, Outcome, SQUASH_SCHEMA, validate_response
        resp = JudgmentResponse("squash", Outcome.COMPLETED, 1, {}, None)
        errors = validate_response(resp, SQUASH_SCHEMA)
        assert any("verified" in e for e in errors)

    def test_squash_schema_accepts_valid_evidence(self):
        from judgment import JudgmentResponse, Outcome, SQUASH_SCHEMA, validate_response
        resp = JudgmentResponse("squash", Outcome.COMPLETED, 1, {"verified": True}, None)
        errors = validate_response(resp, SQUASH_SCHEMA)
        assert errors == []

    def test_squash_schema_rejects_wrong_type(self):
        from judgment import JudgmentResponse, Outcome, SQUASH_SCHEMA, validate_response
        resp = JudgmentResponse("squash", Outcome.COMPLETED, 1, {"verified": "yes"}, None)
        errors = validate_response(resp, SQUASH_SCHEMA)
        assert any("boolean" in e for e in errors)

    def test_evidence_validation_skipped_when_not_completed(self):
        from judgment import JudgmentResponse, Outcome, FORCING_FUNCTION_SCHEMA, validate_response
        resp = JudgmentResponse("forcing_function", Outcome.SKIPPED, 0, {}, None)
        errors = validate_response(resp, FORCING_FUNCTION_SCHEMA)
        assert not any("open_findings" in e for e in errors)


def validate_response_dict(resp_dict: dict, schema: dict) -> list[str]:
    """Test helper — validate a raw dict against schema."""
    errors = []
    required = schema.get("required", [])
    for field in required:
        if field not in resp_dict:
            errors.append(f"missing required field: {field}")
    props = schema.get("properties", {})
    if "outcome" in props and "enum" in props["outcome"]:
        if resp_dict.get("outcome") not in props["outcome"]["enum"]:
            errors.append(f"invalid outcome: {resp_dict.get('outcome')}")
    return errors
