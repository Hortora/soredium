"""Convergence tests — verify re-running work-end after failures converges.

Each test simulates a failure at a specific pipeline point, then verifies
that re-running the orchestrator skips completed steps (via postcondition
checks) and only executes what's remaining.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "verification"))

from close_progress import write_close_progress, read_close_progress


def _make_args(tmp_path, **overrides):
    base = {
        "workspace": str(tmp_path),
        "project": str(tmp_path / "project"),
        "branch": "issue-379-test",
        "base_branch": "main",
        "meta_state": "closing:promoted",
        "on_main": "no",
        "in_slot": "no",
        "covers": "379",
        "issue_repo": "Hortora/soredium",
    }
    base.update(overrides)
    return base


def _prefill_through_review(tmp_path):
    """Pre-fill .close-progress through the review phase."""
    done_steps = {
        "_branch": "issue-379-test",
        "report_init": "done",
        "code_review": "done",
        "branch_audit_conformance": "done",
        "branch_audit_coherence": "done",
        "branch_audit_structure": "done",
        "branch_audit_robustness": "done",
        "loose_ends": "done",
        "forcing_function": "done",
        "sweep_config": "done",
        "sweep_selected": "",
        "review_pass": "done",
    }
    write_close_progress(tmp_path, done_steps)


def _prefill_through_promote(tmp_path):
    """Pre-fill through promotion phase."""
    _prefill_through_review(tmp_path)
    from close_progress import update_close_progress
    update_close_progress(tmp_path, "promote", "done")
    update_close_progress(tmp_path, "report_promote", "done")
    update_close_progress(tmp_path, "promote_pass", "done")
    update_close_progress(tmp_path, "trajectory", "done")


def _prefill_through_land(tmp_path):
    """Pre-fill through land phase."""
    _prefill_through_promote(tmp_path)
    from close_progress import update_close_progress
    update_close_progress(tmp_path, "rebase", "done")
    update_close_progress(tmp_path, "report_rebase", "done")
    update_close_progress(tmp_path, "squash", "done")
    update_close_progress(tmp_path, "report_squash", "done")
    update_close_progress(tmp_path, "land", "done")
    update_close_progress(tmp_path, "report_land", "done")
    update_close_progress(tmp_path, "push_pass", "done")
    update_close_progress(tmp_path, "merge_pass", "done")
    update_close_progress(tmp_path, "stamp_pass", "done")


def _disable_postconditions_on_steps():
    """Disable postcondition_fn on all STEPS for tests that mock execution."""
    from work_end_orchestrator import STEPS
    originals = {}
    for step in STEPS:
        if step.postcondition_fn is not None:
            originals[step.name] = step.postcondition_fn
            step.postcondition_fn = None
    return originals


def _restore_postconditions(originals):
    from work_end_orchestrator import STEPS
    for step in STEPS:
        if step.name in originals:
            step.postcondition_fn = originals[step.name]


class TestIdempotentRerun:
    """Full pipeline re-run with all steps done is a no-op."""

    def test_all_steps_done_returns_complete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("work_end_orchestrator._run_script",
                            lambda cmd, ws, **kw: {})
        monkeypatch.setattr("work_end_orchestrator._final_gate", lambda ctx: None)
        originals = _disable_postconditions_on_steps()
        try:
            _prefill_through_land(tmp_path)
            from close_progress import update_close_progress
            for step in ["close_issues", "report_close_issues",
                         "verify", "report_verify",
                         "checkout_main", "cleanup_stack", "cleanup",
                         "report_scaffold",
                         "arc42_scan", "session_rename", "garden_feedback", "notes",
                         "cleanup_pass", "delete_progress", "report_render"]:
                update_close_progress(tmp_path, step, "done")

            from work_end_orchestrator import run_orchestrator
            result = run_orchestrator(_make_args(tmp_path, meta_state="idle"))
            assert result["ACTION"] == "complete"
        finally:
            _restore_postconditions(originals)


class TestResumeAfterPushFailure:
    """After push fails, re-run skips rebase (postcondition met) and retries push."""

    def test_rebase_not_rerun_when_already_done(self, tmp_path, monkeypatch):
        call_log = []

        def mock_run_script(cmd, ws, **kw):
            cmd_str = " ".join(str(c) for c in cmd)
            call_log.append(cmd_str)
            if "land" in cmd_str:
                return {"LANDED": "yes", "LANDED_SHA": "abc123"}
            return {}

        monkeypatch.setattr("work_end_orchestrator._run_script", mock_run_script)
        originals = _disable_postconditions_on_steps()
        try:
            _prefill_through_promote(tmp_path)
            from close_progress import update_close_progress
            update_close_progress(tmp_path, "rebase", "done")
            update_close_progress(tmp_path, "report_rebase", "done")
            update_close_progress(tmp_path, "squash", "done")
            update_close_progress(tmp_path, "report_squash", "done")

            from work_end_orchestrator import run_orchestrator
            result = run_orchestrator(_make_args(tmp_path))

            rebase_calls = [c for c in call_log
                           if "work_end_execute" in c and " rebase " in c]
            assert len(rebase_calls) == 0, "Rebase script should NOT be called"

            land_calls = [c for c in call_log
                          if "work_end_execute" in c and " land " in c]
            assert len(land_calls) >= 1, "Land script should be called"
        finally:
            _restore_postconditions(originals)


class TestPostconditionSkipOnReentry:
    """Postcondition met on re-entry -> step skipped without executing."""

    def test_promote_skipped_when_stamp_exists(self, tmp_path, monkeypatch):
        script_calls = []

        def mock_run_script(cmd, ws, **kw):
            cmd_str = " ".join(str(c) for c in cmd)
            script_calls.append(cmd_str)
            return {}

        monkeypatch.setattr("work_end_orchestrator._run_script", mock_run_script)

        _prefill_through_review(tmp_path)
        (tmp_path / ".artifacts-promoted").write_text("timestamp=2026-01-01\n")

        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator(_make_args(tmp_path, meta_state="closing:verified"))

        promote_calls = [c for c in script_calls
                         if "promote" in c and "work_end_execute" in c]
        assert len(promote_calls) == 0, "Promote script should NOT run — postcondition met"

        progress = read_close_progress(tmp_path)
        assert progress.get("promote") == "done"


class TestPostconditionVerifyAfterExecution:
    """Postcondition checked after execution — fails if not met."""

    def test_postcondition_failure_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("work_end_orchestrator._run_script",
                            lambda cmd, ws, **kw: {})

        _prefill_through_review(tmp_path)

        from work_end_orchestrator import STEPS
        promote_step = next(s for s in STEPS if s.name == "promote")
        original_pc = promote_step.postcondition_fn

        monkeypatch.setattr(promote_step, "postcondition_fn", lambda ctx: False)

        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator(_make_args(tmp_path, meta_state="closing:verified"))

        assert result.get("ERROR") == "postcondition_failed"
        assert result.get("STEP") == "promote"

        monkeypatch.setattr(promote_step, "postcondition_fn", original_pc)


class TestProgressSurvivesRestart:
    """Progress file tracks completed steps across restarts."""

    def test_completed_steps_survive_restart(self, tmp_path, monkeypatch):
        monkeypatch.setattr("work_end_orchestrator._run_script",
                            lambda cmd, ws, **kw: {})
        originals = _disable_postconditions_on_steps()
        try:
            _prefill_through_land(tmp_path)

            progress = read_close_progress(tmp_path)
            assert progress.get("rebase") == "done"
            assert progress.get("land") == "done"
            assert progress.get("promote") == "done"

            from work_end_orchestrator import run_orchestrator
            result = run_orchestrator(_make_args(tmp_path, meta_state="closing:stamped"))

            assert result["ACTION"] in ("user_input", "complete")
        finally:
            _restore_postconditions(originals)


class TestMultipleStepSkips:
    """Multiple consecutive postcondition skips work correctly."""

    def test_multiple_postcondition_skips(self, tmp_path, monkeypatch):
        """When promote and rebase postconditions are both met, both skip."""
        script_calls = []

        def mock_run_script(cmd, ws, **kw):
            cmd_str = " ".join(str(c) for c in cmd)
            script_calls.append(cmd_str)
            return {}

        monkeypatch.setattr("work_end_orchestrator._run_script", mock_run_script)

        _prefill_through_promote(tmp_path)
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "trajectory", "done")
        update_close_progress(tmp_path, "squash", "done")

        from work_end_orchestrator import STEPS

        rebase_step = next(s for s in STEPS if s.name == "rebase")
        land_step = next(s for s in STEPS if s.name == "land")
        monkeypatch.setattr(rebase_step, "postcondition_fn", lambda ctx: True)
        monkeypatch.setattr(land_step, "postcondition_fn", lambda ctx: True)

        remaining_steps = [s for s in STEPS
                           if s.step_type == "mechanical"
                           and s.name not in ("rebase", "land")
                           and s.postcondition_fn is not None]
        for step in remaining_steps:
            monkeypatch.setattr(step, "postcondition_fn", None)

        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator(_make_args(tmp_path, meta_state="closing:promoted"))

        rebase_script_calls = [c for c in script_calls
                               if "work_end_execute" in c and " rebase " in c]
        assert len(rebase_script_calls) == 0, "Rebase should be skipped"

        land_script_calls = [c for c in script_calls
                             if "work_end_execute" in c and " land " in c]
        assert len(land_script_calls) == 0, "Land should be skipped"

        progress = read_close_progress(tmp_path)
        assert progress.get("rebase") == "done"
        assert progress.get("land") == "done"
