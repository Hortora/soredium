"""Typed step results for lifecycle orchestrators.

Replaces untyped dict[str, str] returns from mechanical steps with
structured results that enable deterministic retry/abort decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ResultStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"

    def is_ok(self) -> bool:
        return self in (ResultStatus.SUCCESS, ResultStatus.SKIPPED,
                        ResultStatus.NOT_APPLICABLE)


class ErrorKind(Enum):
    RETRYABLE = "retryable"
    FATAL = "fatal"
    BLOCKED_BY = "blocked_by"


@dataclass(frozen=True)
class StepError:
    kind: ErrorKind
    message: str
    blocked_by: str | None = None


@dataclass(frozen=True)
class StepResult:
    status: ResultStatus
    error: StepError | None = None
    produced: int = 0
    output: dict[str, str] | None = None

    def is_ok(self) -> bool:
        return self.status.is_ok()

    def is_retryable(self) -> bool:
        return (self.error is not None
                and self.error.kind == ErrorKind.RETRYABLE)

    @classmethod
    def success(cls, produced: int = 0, output: dict[str, str] | None = None) -> StepResult:
        return cls(ResultStatus.SUCCESS, produced=produced, output=output)

    @classmethod
    def failed(cls, message: str, kind: ErrorKind = ErrorKind.RETRYABLE,
               output: dict[str, str] | None = None) -> StepResult:
        return cls(ResultStatus.FAILED,
                   error=StepError(kind, message), output=output)

    @classmethod
    def blocked_by(cls, step: str) -> StepResult:
        return cls(ResultStatus.FAILED,
                   error=StepError(ErrorKind.BLOCKED_BY,
                                   f"blocked by {step}", blocked_by=step))

    @classmethod
    def skipped(cls) -> StepResult:
        return cls(ResultStatus.SKIPPED)

    @classmethod
    def not_applicable(cls) -> StepResult:
        return cls(ResultStatus.NOT_APPLICABLE)

    @classmethod
    def from_script_output(cls, output: dict[str, str]) -> StepResult:
        if "ERROR" in output:
            error_msg = output.get("ERROR", "unknown")
            detail = output.get("ERROR_DETAIL", "")
            msg = f"{error_msg}: {detail}" if detail else error_msg
            return cls.failed(msg, output=output)
        return cls.success(output=output)
