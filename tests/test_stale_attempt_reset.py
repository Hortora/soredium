"""Tests for stale mechanical attempt counter reset on re-entry (#454).

When a mechanical step hits MAX_MECHANICAL_RETRIES and escalates to
user_input, re-invoking the orchestrator (after fixing code) should
reset the counter so the step can re-execute with fresh retries.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from verification.outcomes import VerifyResult, Verification
from shared_steps import StepDef, MAX_MECHANICAL_RETRIES
from judgment import StepType
from work_progress import read_progress
from progress import Progress


@dataclass
class FakeCtx:
    workspace: Path
    project: Path
    branch: str = "test"
    base_branch: str = "main"
    on_main: bool = False
    in_slot: bool = False
    covers: str = ""
    issue_repo: str = ""
    progress: Progress = field(default_factory=Progress)
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


class TestStaleCounterResetsOnReentry:
    """Mechanical steps with stale attempt counters get fresh retries (#454)."""

    def test_at_max_resets_and_executes(self, tmp_path):
        """A step at MAX_MECHANICAL_RETRIES should reset and re-execute."""
        from orchestrator_engine import run_loop

        executed = []

        def outcome_fn(ctx):
            return Verification("test_check", VerifyResult.UNKNOWN, {}, "")

        step = StepDef(
            name="land", phase="test", step_type=StepType.MECHANICAL,
            outcome_fn=outcome_fn,
            idempotent=False,
        )

        progress = Progress()
        progress.set("land_mechanical_attempt", str(MAX_MECHANICAL_RETRIES))
        progress.save(tmp_path)

        ctx = FakeCtx(workspace=tmp_path, project=tmp_path, progress=progress)

        def mock_execute(step, ctx):
            executed.append(step.name)
            return {}

        result = run_loop([step], ctx, execute_mechanical_fn=mock_execute)

        assert result.get("ACTION") != "user_input", (
            "Step should not immediately escalate with stale counter"
        )

    def test_above_max_also_resets(self, tmp_path):
        """Counter above MAX (e.g. 5) should also reset."""
        from orchestrator_engine import run_loop

        def outcome_fn(ctx):
            return Verification("test_check", VerifyResult.UNKNOWN, {}, "")

        step = StepDef(
            name="land", phase="test", step_type=StepType.MECHANICAL,
            outcome_fn=outcome_fn,
            idempotent=False,
        )

        progress = Progress()
        progress.set("land_mechanical_attempt", "5")
        progress.save(tmp_path)

        ctx = FakeCtx(workspace=tmp_path, project=tmp_path, progress=progress)

        result = run_loop([step], ctx, execute_mechanical_fn=lambda s, c: {})

        assert result.get("ACTION") != "user_input"

    def test_below_max_not_reset(self, tmp_path):
        """Counter below MAX should NOT be reset — genuine in-progress retry."""
        from orchestrator_engine import run_loop

        def outcome_fn(ctx):
            return Verification("test_check", VerifyResult.UNKNOWN, {}, "")

        step = StepDef(
            name="land", phase="test", step_type=StepType.MECHANICAL,
            outcome_fn=outcome_fn,
            idempotent=False,
        )

        progress = Progress()
        progress.set("land_mechanical_attempt", "1")
        progress.save(tmp_path)

        ctx = FakeCtx(workspace=tmp_path, project=tmp_path, progress=progress)

        result = run_loop([step], ctx, execute_mechanical_fn=lambda s, c: {})

        assert result.get("ACTION") == "error"
        assert result.get("ERROR") == "unknown_verification"

    def test_reset_persists_to_disk(self, tmp_path):
        """After reset, the progress file should reflect the new counter."""
        from orchestrator_engine import run_loop

        def outcome_fn(ctx):
            return Verification("test_check", VerifyResult.PASS, {}, "")

        step = StepDef(
            name="land", phase="test", step_type=StepType.MECHANICAL,
            outcome_fn=outcome_fn,
        )

        progress = Progress()
        progress.set("land_mechanical_attempt", str(MAX_MECHANICAL_RETRIES))
        progress.save(tmp_path)

        ctx = FakeCtx(workspace=tmp_path, project=tmp_path, progress=progress)

        run_loop([step], ctx, execute_mechanical_fn=lambda s, c: {})

        disk_progress = read_progress(tmp_path)
        attempt = int(disk_progress.get("land_mechanical_attempt", "99"))
        assert attempt < MAX_MECHANICAL_RETRIES

    def test_reset_allows_full_retry_cycle(self, tmp_path):
        """After reset, step can fail and increment through a full new cycle."""
        from orchestrator_engine import run_loop

        call_count = [0]

        def outcome_fn(ctx):
            call_count[0] += 1
            return Verification("test_check", VerifyResult.UNKNOWN, {}, "")

        step = StepDef(
            name="land", phase="test", step_type=StepType.MECHANICAL,
            outcome_fn=outcome_fn,
            idempotent=False,
        )

        progress = Progress()
        progress.set("land_mechanical_attempt", str(MAX_MECHANICAL_RETRIES))
        progress.save(tmp_path)

        ctx = FakeCtx(workspace=tmp_path, project=tmp_path, progress=progress)

        result = run_loop([step], ctx, execute_mechanical_fn=lambda s, c: {})

        # After reset (attempt=0), pre-exec UNKNOWN with attempt=0
        # falls through (0 > 0 is false), step executes, then post-exec
        # UNKNOWN increments to 1 and returns error for retry
        assert call_count[0] >= 2, "outcome_fn should be called at least twice (pre + post exec)"

    def test_step_done_already_no_reset_needed(self, tmp_path):
        """If step is already done, counter is irrelevant (no regression)."""
        from orchestrator_engine import run_loop

        step = StepDef(
            name="land", phase="test", step_type=StepType.MECHANICAL,
            outcome_fn=lambda ctx: Verification("c", VerifyResult.UNKNOWN, {}, ""),
        )

        progress = Progress()
        progress.set("land", "done")
        progress.set("land_mechanical_attempt", str(MAX_MECHANICAL_RETRIES))
        progress.save(tmp_path)

        ctx = FakeCtx(workspace=tmp_path, project=tmp_path, progress=progress)

        result = run_loop([step], ctx)

        assert result["ACTION"] == "complete"
