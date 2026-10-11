"""Tests for project/step_result.py — typed step results."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
from step_result import StepResult, ResultStatus, ErrorKind, StepError


class TestResultStatus:
    def test_success_is_ok(self):
        assert ResultStatus.SUCCESS.is_ok()
        assert not ResultStatus.FAILED.is_ok()
        assert ResultStatus.SKIPPED.is_ok()
        assert ResultStatus.NOT_APPLICABLE.is_ok()

    def test_failed_is_not_ok(self):
        assert not ResultStatus.FAILED.is_ok()


class TestStepResult:
    def test_success(self):
        r = StepResult.success()
        assert r.status == ResultStatus.SUCCESS
        assert r.error is None
        assert r.produced == 0

    def test_success_with_produced(self):
        r = StepResult.success(produced=5)
        assert r.produced == 5

    def test_failed_retryable(self):
        r = StepResult.failed("network timeout", kind=ErrorKind.RETRYABLE)
        assert r.status == ResultStatus.FAILED
        assert r.error is not None
        assert r.error.kind == ErrorKind.RETRYABLE
        assert r.error.message == "network timeout"
        assert r.is_retryable()

    def test_failed_fatal(self):
        r = StepResult.failed("missing file", kind=ErrorKind.FATAL)
        assert r.status == ResultStatus.FAILED
        assert not r.is_retryable()

    def test_failed_blocked(self):
        r = StepResult.blocked_by("rebase")
        assert r.status == ResultStatus.FAILED
        assert r.error.kind == ErrorKind.BLOCKED_BY
        assert r.error.blocked_by == "rebase"

    def test_skipped(self):
        r = StepResult.skipped()
        assert r.status == ResultStatus.SKIPPED
        assert r.is_ok()

    def test_not_applicable(self):
        r = StepResult.not_applicable()
        assert r.status == ResultStatus.NOT_APPLICABLE
        assert r.is_ok()

    def test_from_script_output_success(self):
        output = {"PROMOTED": "3"}
        r = StepResult.from_script_output(output)
        assert r.status == ResultStatus.SUCCESS

    def test_from_script_output_error(self):
        output = {"ERROR": "timeout", "ERROR_DETAIL": "script hung"}
        r = StepResult.from_script_output(output)
        assert r.status == ResultStatus.FAILED
        assert "timeout" in r.error.message

    def test_from_script_output_empty(self):
        r = StepResult.from_script_output({})
        assert r.status == ResultStatus.SUCCESS
