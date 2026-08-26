"""Tests for work-end/work_end_orchestrator.py — close sequence orchestrator."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))


class TestRunScript:
    """_run_script calls subprocess and parses KEY=VALUE output."""

    def test_parses_output(self, tmp_path):
        script = tmp_path / "echo_script.py"
        script.write_text('print("RESULT=ok")\nprint("COUNT=3")\n')
        from work_end_orchestrator import _run_script
        result = _run_script([sys.executable, str(script)], tmp_path)
        assert result == {"RESULT": "ok", "COUNT": "3"}

    def test_captures_error(self, tmp_path):
        script = tmp_path / "fail_script.py"
        script.write_text('import sys; print("ERROR=boom"); sys.exit(1)\n')
        from work_end_orchestrator import _run_script
        result = _run_script([sys.executable, str(script)], tmp_path)
        assert result.get("ERROR") == "boom"

    def test_non_zero_exit_without_error_key(self, tmp_path):
        script = tmp_path / "silent_fail.py"
        script.write_text('import sys; sys.exit(1)\n')
        from work_end_orchestrator import _run_script
        result = _run_script([sys.executable, str(script)], tmp_path)
        assert "ERROR" in result

    def test_dry_run_captures_without_executing(self, tmp_path):
        from work_end_orchestrator import _run_script
        calls = []
        result = _run_script(
            ["python3", "work-end/work_end_execute.py", "promote"],
            tmp_path, dry_run=True, call_log=calls,
        )
        assert len(calls) == 1
        assert "promote" in str(calls[0])
        assert result == {}

    def test_script_not_found(self, tmp_path):
        from work_end_orchestrator import _run_script
        result = _run_script(["/nonexistent/script.py"], tmp_path)
        assert "ERROR" in result


class TestOrchestratorFirstCall:
    """First call with no progress — should yield ACTION=review."""

    def test_yields_review_on_first_call(self, tmp_path, monkeypatch):
        monkeypatch.setattr("work_end_orchestrator._run_script", lambda cmd, ws, **kw: {})
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
        })
        assert result["ACTION"] == "review"

    def test_includes_diff_range(self, tmp_path, monkeypatch):
        monkeypatch.setattr("work_end_orchestrator._run_script", lambda cmd, ws, **kw: {})
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
        })
        assert "DIFF_RANGE" in result


class TestOrchestratorSequence:
    """Steps yield in correct order as progress advances."""

    def _run(self, tmp_path, meta_state="closing:review", **extra):
        from work_end_orchestrator import run_orchestrator
        args = {
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": meta_state,
        }
        args.update(extra)
        return run_orchestrator(args)

    def test_review_then_sweep_config(self, tmp_path):
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        result = self._run(tmp_path)
        assert result["ACTION"] == "sweep_config"

    def test_sweep_config_then_first_selected_step(self, tmp_path):
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage,write_content")
        result = self._run(tmp_path)
        assert result["ACTION"] == "forage"

    def test_skips_deselected_sweep_steps(self, tmp_path):
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "write_content")
        update_close_progress(tmp_path, "forage", "skipped")
        update_close_progress(tmp_path, "protocol", "skipped")
        update_close_progress(tmp_path, "update_claude_md", "skipped")
        update_close_progress(tmp_path, "impl_doc_sync", "skipped")
        update_close_progress(tmp_path, "adr", "skipped")
        result = self._run(tmp_path)
        assert result["ACTION"] == "write_content"

    def test_all_sweep_done_yields_no_more_sweep(self, tmp_path, monkeypatch):
        """After all sweep sub-steps done, next call should trigger
        mechanical steps (lifecycle transition) and yield trajectory."""
        monkeypatch.setattr("work_end_orchestrator._run_script", lambda cmd, ws, **kw: {})
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "report_init", "done")
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage")
        update_close_progress(tmp_path, "forage", "done")
        result = self._run(tmp_path, meta_state="closing:promoted")
        assert result["ACTION"] == "trajectory"


class TestSweepConfigAll:
    """When all sweep items are deselected, no sweep actions yield."""

    def test_empty_selection_skips_to_post_sweep(self, tmp_path, monkeypatch):
        monkeypatch.setattr("work_end_orchestrator._run_script", lambda cmd, ws, **kw: {})
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "report_init", "done")
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "")
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:promoted",
        })
        assert result["ACTION"] == "trajectory"


class TestMainMode:
    """Main mode skips rebase, squash, stamp-related steps."""

    def test_main_mode_skips_to_post_land(self, tmp_path, monkeypatch):
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
        monkeypatch.setattr("work_end_orchestrator._run_script", lambda cmd, ws, **kw: {})
        monkeypatch.setattr("work_end_orchestrator._push_main_mode", lambda ctx: {"PUSHED": "yes", "LANDED_SHA": "abc"})
        monkeypatch.setattr("work_end_orchestrator._verify_main_mode", lambda ctx: {"VERIFIED": "yes"})
        monkeypatch.setattr("work_end_orchestrator._cleanup_main_mode", lambda ctx: {"CLEANED": "yes"})
        for step in ["report_init", "review", "sweep_config",
                     "review_pass", "promote", "report_promote", "promote_pass",
                     "trajectory"]:
            update_close_progress(tmp_path, step, "done")
        update_close_progress(tmp_path, "sweep_selected", "")
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:promoted",
            "on_main": "yes",
        })
        assert result["ACTION"] == "user_input" or result["ACTION"] == "complete"


class TestAbort:
    """Abort from allowed and disallowed states."""

    def test_abort_from_review(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "abort": "yes",
        })
        assert result["ACTION"] == "complete"
        assert "Aborted" in result.get("SUMMARY", "")

    def test_abort_from_promoted_rejected(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:promoted",
            "abort": "yes",
        })
        assert "ERROR" in result or result["ACTION"] == "error"


class TestStaleProgress:
    """Stale progress from prior close is detected and cleaned."""

    def test_stale_progress_deleted(self, tmp_path):
        from close_progress import write_close_progress, read_close_progress
        write_close_progress(tmp_path, {
            "review": "done", "promote": "done", "land": "done",
        })
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
        })
        assert result["ACTION"] == "review"
        progress = read_close_progress(tmp_path)
        assert "land" not in progress


class TestRetry:
    """Judgment step retry counting."""

    def test_retry_escalates_after_3(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "write_content")
        update_close_progress(tmp_path, "write_content_attempt", "3")
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
        })
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "step_failed"
        assert result.get("STEP") == "write_content"

    def test_step_failed_records_to_worklog(self, tmp_path, monkeypatch):
        """step_failed writes a step-failed event to the worklog DB."""
        import json
        db_path = str(tmp_path / "worklog.db")
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import worklog
        mock_wl = type(sys)("mock_wl")
        mock_wl.connect = lambda: worklog.connect(db_path)
        mock_wl.record_close_event = worklog.record_close_event
        monkeypatch.setattr("work_end_orchestrator._wl", mock_wl)
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage")
        update_close_progress(tmp_path, "forage_attempt", "3")
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "covers": "271",
            "issue_repo": "Hortora/soredium",
        })
        assert result.get("CONTEXT") == "step_failed"
        conn = worklog.connect(db_path)
        events = worklog.event_log(conn, event_type="step-failed")
        assert len(events) == 1
        meta = json.loads(events[0]["metadata"])
        assert meta["step"] == "forage"
        assert meta["mode"] == "close"
        assert meta["attempts"] == 3
        conn.close()


class TestStepDoneValidation:
    """step_done= rejects mechanical steps."""

    def test_rejects_mechanical_step_done(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "step_done": "promote",
        })
        assert result.get("ERROR") == "invalid_step_done"

    def test_accepts_judgment_step_done(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "step_done": "review",
        })
        assert result.get("ERROR") != "invalid_step_done"


class TestSkipStep:
    """skip_step= argument marks a step as skipped."""

    def _run(self, tmp_path, **extra):
        from work_end_orchestrator import run_orchestrator
        args = {
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
        }
        args.update(extra)
        return run_orchestrator(args)

    def test_skip_step_marks_skipped(self, tmp_path):
        from close_progress import update_close_progress, read_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage,write_content")
        self._run(tmp_path, skip_step="forage")
        progress = read_close_progress(tmp_path)
        assert progress.get("forage") == "skipped"

    def test_skip_matches_last_yielded(self, tmp_path):
        """Skip succeeds when skip_step matches what was last yielded."""
        from close_progress import update_close_progress, read_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage,write_content")
        # First call yields forage (sets last_yielded=forage)
        result = self._run(tmp_path)
        assert result["ACTION"] == "forage"
        # Skip forage — matches last_yielded
        result = self._run(tmp_path, skip_step="forage")
        assert result.get("ERROR") != "invalid_skip"
        progress = read_close_progress(tmp_path)
        assert progress.get("forage") == "skipped"

    def test_skip_rejects_non_yielded_step(self, tmp_path):
        """Skip fails when skip_step doesn't match last_yielded."""
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage,write_content")
        # Yield forage (sets last_yielded=forage)
        result = self._run(tmp_path)
        assert result["ACTION"] == "forage"
        # Try to skip write_content — doesn't match last_yielded
        result = self._run(tmp_path, skip_step="write_content")
        assert result.get("ERROR") == "invalid_skip"
        assert result.get("LAST_YIELDED") == "forage"

    def test_cannot_skip_ahead_past_yielded_step(self, tmp_path):
        """Cannot skip write_content when protocol was just yielded."""
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage,protocol,write_content")
        # Yield forage
        result = self._run(tmp_path)
        assert result["ACTION"] == "forage"
        # Skip forage — orchestrator yields protocol next (last_yielded=protocol)
        result = self._run(tmp_path, skip_step="forage")
        assert result["ACTION"] == "protocol"
        # Try to skip write_content when protocol was just yielded — blocked
        result = self._run(tmp_path, skip_step="write_content")
        assert result.get("ERROR") == "invalid_skip"
        assert result.get("LAST_YIELDED") == "protocol"

    def test_step_done_allows_next_step_to_yield(self, tmp_path):
        """step_done advances the sequence; next yield overwrites last_yielded."""
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage,write_content")
        # Yield forage
        result = self._run(tmp_path)
        assert result["ACTION"] == "forage"
        # Complete forage via step_done
        result = self._run(tmp_path, step_done="forage")
        # Should yield write_content next
        assert result["ACTION"] == "write_content"


class TestIntegrationBranchMode:
    """Full branch-mode sequence — walk through all orchestrator calls."""

    def _call(self, tmp_path, meta_state="closing:review", **extra):
        from work_end_orchestrator import run_orchestrator
        args = {
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": meta_state,
            "covers": "271",
            "issue_repo": "Hortora/soredium",
        }
        args.update(extra)
        return run_orchestrator(args)

    def _complete(self, tmp_path, step):
        from close_progress import update_close_progress
        update_close_progress(tmp_path, step, "done")

    def test_full_branch_sequence(self, tmp_path, monkeypatch):
        """Walk through the complete branch-mode close sequence."""
        def mock_run(cmd, workspace, **kw):
            return {"REBASED": "yes", "LANDED": "yes", "LANDED_SHA": "abc123",
                    "CLOSED": "1", "VERIFIED": "yes", "SWITCHED": "yes",
                    "CLEANED": "yes"}
        monkeypatch.setattr("work_end_orchestrator._run_script", mock_run)

        actions_seen = []

        result = self._call(tmp_path)
        assert result["ACTION"] == "review"
        actions_seen.append("review")
        self._complete(tmp_path, "review")

        result = self._call(tmp_path)
        assert result["ACTION"] == "sweep_config"
        actions_seen.append("sweep_config")
        self._complete(tmp_path, "sweep_config")

        result = self._call(tmp_path, sweep_selected="forage,write_content")
        assert result["ACTION"] == "forage"
        actions_seen.append("forage")
        self._complete(tmp_path, "forage")

        result = self._call(tmp_path)
        assert result["ACTION"] == "write_content"
        actions_seen.append("write_content")
        self._complete(tmp_path, "write_content")

        result = self._call(tmp_path, meta_state="closing:promoted")
        assert result["ACTION"] == "trajectory"
        actions_seen.append("trajectory")
        self._complete(tmp_path, "trajectory")

        result = self._call(tmp_path, meta_state="closing:promoted")
        assert result["ACTION"] == "squash"
        actions_seen.append("squash")
        self._complete(tmp_path, "squash")

        result = self._call(tmp_path, meta_state="closing:stamped")
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "arc42_scan"
        actions_seen.append("arc42_scan")
        self._complete(tmp_path, "arc42_scan")

        result = self._call(tmp_path, meta_state="closing:stamped")
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "session_rename"
        actions_seen.append("session_rename")
        self._complete(tmp_path, "session_rename")

        result = self._call(tmp_path, meta_state="closing:stamped")
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "garden_feedback"
        actions_seen.append("garden_feedback")
        self._complete(tmp_path, "garden_feedback")

        result = self._call(tmp_path, meta_state="closing:stamped")
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "notes"
        actions_seen.append("notes")
        self._complete(tmp_path, "notes")

        result = self._call(tmp_path, meta_state="closing:stamped")
        assert result["ACTION"] == "complete"
        actions_seen.append("complete")

        expected = [
            "review", "sweep_config", "forage", "write_content",
            "trajectory", "squash",
            "arc42_scan", "session_rename", "garden_feedback", "notes",
            "complete",
        ]
        assert actions_seen == expected

    def test_main_mode_skips_squash(self, tmp_path, monkeypatch):
        """Main mode skips rebase and squash, goes straight to cleanup."""
        from close_progress import update_close_progress
        monkeypatch.setattr("work_end_orchestrator._run_script", lambda cmd, ws, **kw: {})
        monkeypatch.setattr("work_end_orchestrator._push_main_mode", lambda ctx: {"PUSHED": "yes", "LANDED_SHA": "abc"})
        monkeypatch.setattr("work_end_orchestrator._verify_main_mode", lambda ctx: {"VERIFIED": "yes"})
        monkeypatch.setattr("work_end_orchestrator._cleanup_main_mode", lambda ctx: {"CLEANED": "yes"})
        for step in ["report_init", "review", "sweep_config",
                     "review_pass", "promote", "report_promote", "promote_pass",
                     "trajectory"]:
            update_close_progress(tmp_path, step, "done")
        update_close_progress(tmp_path, "sweep_selected", "")
        result = self._call(tmp_path, meta_state="closing:stamped", on_main="yes")
        assert result["ACTION"] == "user_input"

    def test_no_covers_skips_close_issues(self, tmp_path, monkeypatch):
        """When covers is empty, close_issues step is skipped."""
        def mock_run(cmd, workspace, **kw):
            return {"VERIFIED": "yes", "SWITCHED": "yes", "CLEANED": "yes"}
        monkeypatch.setattr("work_end_orchestrator._run_script", mock_run)
        from close_progress import update_close_progress, read_close_progress
        for step in ["review", "sweep_config", "trajectory", "squash",
                     "rebase", "land", "arc42_scan", "session_rename",
                     "garden_feedback", "notes", "verify", "cleanup",
                     "checkout_main", "cleanup_stack"]:
            update_close_progress(tmp_path, step, "done")
        update_close_progress(tmp_path, "sweep_selected", "")

        result = self._call(tmp_path, meta_state="closing:stamped",
                            covers="")
        assert result["ACTION"] == "complete"
        progress = read_close_progress(tmp_path)
        assert "close_issues" not in progress


class TestIntegrationCrashRecovery:
    """Crash recovery — resume from mid-sequence."""

    def _call(self, tmp_path, meta_state="closing:review", **extra):
        from work_end_orchestrator import run_orchestrator
        args = {
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": meta_state,
        }
        args.update(extra)
        return run_orchestrator(args)

    def test_resume_after_review(self, tmp_path):
        """After crash, review was done — resumes at sweep_config."""
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        result = self._call(tmp_path)
        assert result["ACTION"] == "sweep_config"

    def test_resume_after_sweep(self, tmp_path, monkeypatch):
        """After crash, review+sweep done — resumes at trajectory."""
        monkeypatch.setattr("work_end_orchestrator._run_script", lambda cmd, ws, **kw: {})
        from close_progress import update_close_progress
        for step in ["report_init", "review", "sweep_config"]:
            update_close_progress(tmp_path, step, "done")
        update_close_progress(tmp_path, "sweep_selected", "forage")
        update_close_progress(tmp_path, "forage", "done")
        result = self._call(tmp_path, meta_state="closing:promoted")
        assert result["ACTION"] == "trajectory"

    def test_resume_mid_cleanup(self, tmp_path, monkeypatch):
        """After crash during cleanup, resumes at next user_input."""
        def mock_run(cmd, workspace, **kw):
            return {"CLOSED": "1", "VERIFIED": "yes", "SWITCHED": "yes", "CLEANED": "yes"}
        monkeypatch.setattr("work_end_orchestrator._run_script", mock_run)
        from close_progress import update_close_progress
        for step in ["review", "sweep_config", "trajectory", "squash",
                     "rebase", "land", "verify", "arc42_scan",
                     "close_issues"]:
            update_close_progress(tmp_path, step, "done")
        update_close_progress(tmp_path, "sweep_selected", "")
        result = self._call(tmp_path, meta_state="closing:stamped",
                            covers="271", issue_repo="Hortora/soredium")
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "session_rename"

    def test_progress_file_survives_atomic_write(self, tmp_path):
        """Verify .close-progress survives the atomic write pattern."""
        from close_progress import (
            update_close_progress, read_close_progress,
            write_close_progress,
        )
        write_close_progress(tmp_path, {"review": "done", "sweep_config": "done"})
        update_close_progress(tmp_path, "forage", "done")
        progress = read_close_progress(tmp_path)
        assert progress == {"review": "done", "sweep_config": "done", "forage": "done"}

    def test_stale_progress_from_prior_close_cleaned(self, tmp_path):
        """Progress from a completed prior close is detected and removed."""
        from close_progress import write_close_progress, read_close_progress
        write_close_progress(tmp_path, {
            "review": "done", "promote": "done",
            "land": "done", "cleanup": "done",
        })
        result = self._call(tmp_path, meta_state="closing:review")
        assert result["ACTION"] == "review"
        progress = read_close_progress(tmp_path)
        assert "land" not in progress
        assert "cleanup" not in progress


class TestStepSequence:
    """STEPS data structure covers all required steps in correct order."""

    def test_covers_all_mechanical_steps(self):
        from work_end_orchestrator import STEPS
        step_names = [s.name for s in STEPS]
        for name in ["rebase", "land", "close_issues", "verify", "cleanup"]:
            assert name in step_names, f"Missing mechanical step: {name}"

    def test_covers_all_judgment_steps(self):
        from work_end_orchestrator import STEPS
        step_names = [s.name for s in STEPS]
        for name in ["review", "sweep_config", "forage", "protocol",
                     "update_claude_md", "impl_doc_sync", "adr",
                     "write_content", "trajectory", "squash",
                     "arc42_scan", "session_rename", "garden_feedback", "notes"]:
            assert name in step_names, f"Missing judgment step: {name}"

    def test_phase_ordering(self):
        from work_end_orchestrator import STEPS
        phase_order = [
            "closing:review", "closing:verified", "closing:promoted",
            "closing:pushed", "closing:merged", "closing:stamped", "idle",
        ]
        last_phase_idx = 0
        for step in STEPS:
            if step.phase in phase_order:
                idx = phase_order.index(step.phase)
                assert idx >= last_phase_idx, (
                    f"Step {step.name} (phase {step.phase}) is out of order "
                    f"(after phase {phase_order[last_phase_idx]})"
                )
                last_phase_idx = idx

    def test_stamped_phase_internal_ordering(self):
        from work_end_orchestrator import STEPS
        stamped = [s.name for s in STEPS if s.phase == "closing:stamped"]
        if "arc42_scan" in stamped and "close_issues" in stamped:
            assert stamped.index("close_issues") < stamped.index("arc42_scan"), (
                "close_issues must come before arc42_scan in closing:stamped"
            )


class TestMechanicalStepWiring:
    """Mechanical steps call real scripts via _run_script, not stubs."""

    def _setup_to_step(self, tmp_path, target_step, meta_state="closing:review",
                       on_main="no", in_slot="no", covers="271"):
        """Mark all steps before target_step as done."""
        from work_end_orchestrator import STEPS
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "sweep_selected", "")
        for step in STEPS:
            if step.name == target_step:
                break
            if step.step_type == "judgment":
                update_close_progress(tmp_path, step.name, "done")
            elif step.step_type == "mechanical":
                update_close_progress(tmp_path, step.name, "done")

    def _run(self, tmp_path, meta_state="closing:review", **extra):
        from work_end_orchestrator import run_orchestrator
        args = {
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": meta_state,
            "covers": "271",
            "issue_repo": "Hortora/soredium",
        }
        args.update(extra)
        return run_orchestrator(args)

    def test_rebase_calls_work_end_execute(self, tmp_path, monkeypatch):
        """rebase step calls work_end_execute.py rebase with correct args."""
        calls = []
        def capture(cmd, workspace, **kw):
            calls.append(cmd)
            return {"REBASED": "yes"}
        monkeypatch.setattr("work_end_orchestrator._run_script", capture)
        self._setup_to_step(tmp_path, "rebase", meta_state="closing:promoted")
        self._run(tmp_path, meta_state="closing:promoted")
        rebase_calls = [c for c in calls if any("rebase" in str(a) for a in c)]
        assert len(rebase_calls) >= 1, f"Expected rebase call, got: {calls}"

    def test_land_branch_mode_calls_work_end_execute(self, tmp_path, monkeypatch):
        """Branch mode land calls work_end_execute.py land."""
        calls = []
        def capture(cmd, workspace, **kw):
            calls.append(cmd)
            return {"LANDED": "yes", "LANDED_SHA": "abc123"}
        monkeypatch.setattr("work_end_orchestrator._run_script", capture)
        self._setup_to_step(tmp_path, "land", meta_state="closing:promoted")
        self._run(tmp_path, meta_state="closing:promoted")
        land_calls = [c for c in calls if any("land" in str(a) for a in c)]
        assert any("work_end_execute.py" in str(c) for c in land_calls), f"Expected land call, got: {calls}"

    def test_land_slot_mode_calls_per_repo(self, tmp_path, monkeypatch):
        """Slot mode land calls work_end_execute.py land per repo."""
        calls = []
        def capture(cmd, workspace, **kw):
            calls.append(cmd)
            return {"LANDED": "yes", "LANDED_SHA": "abc123"}
        monkeypatch.setattr("work_end_orchestrator._run_script", capture)
        self._setup_to_step(tmp_path, "land", meta_state="closing:promoted")
        slot_path = tmp_path / "slot"
        slot_path.mkdir()
        (slot_path / ".slot").write_text("## Repos\n- alpha (primary)\n- beta\n")
        (slot_path / "alpha").mkdir()
        (slot_path / "beta").mkdir()
        self._run(tmp_path, meta_state="closing:promoted",
                  in_slot="yes", slot_path=str(slot_path))
        land_calls = [c for c in calls if any("land" in str(a) for a in c) and any("work_end_execute" in str(a) for a in c)]
        assert len(land_calls) >= 1, f"Expected per-repo land call, got: {calls}"

    def test_close_issues_calls_work_end_execute(self, tmp_path, monkeypatch):
        """close_issues step calls work_end_execute.py close-issues."""
        calls = []
        def capture(cmd, workspace, **kw):
            calls.append(cmd)
            return {"CLOSED": "1"}
        monkeypatch.setattr("work_end_orchestrator._run_script", capture)
        self._setup_to_step(tmp_path, "close_issues", meta_state="closing:stamped")
        self._run(tmp_path, meta_state="closing:stamped")
        close_calls = [c for c in calls if any("close-issues" in str(a) for a in c)]
        assert len(close_calls) >= 1, f"Expected close-issues call, got: {calls}"

    def test_verify_calls_verify_slot_close(self, tmp_path, monkeypatch):
        """verify step calls verify_slot_close.py."""
        calls = []
        def capture(cmd, workspace, **kw):
            calls.append(cmd)
            return {"VERIFIED": "yes"}
        monkeypatch.setattr("work_end_orchestrator._run_script", capture)
        self._setup_to_step(tmp_path, "verify", meta_state="closing:stamped")
        self._run(tmp_path, meta_state="closing:stamped")
        verify_calls = [c for c in calls if any("verify" in str(a) for a in c)]
        assert len(verify_calls) >= 1, f"Expected verify call, got: {calls}"

    def test_main_mode_skips_rebase(self, tmp_path, monkeypatch):
        """Main mode skips rebase — no script call."""
        calls = []
        def capture(cmd, workspace, **kw):
            calls.append(cmd)
            return {}
        monkeypatch.setattr("work_end_orchestrator._run_script", capture)
        self._setup_to_step(tmp_path, "rebase", meta_state="closing:promoted")
        self._run(tmp_path, meta_state="closing:promoted", on_main="yes")
        rebase_calls = [c for c in calls if any("rebase" in str(a) for a in c)]
        assert len(rebase_calls) == 0, "Main mode should NOT call rebase"


class TestReconciliation:
    """Evidence-based recovery corrects false progress on startup."""

    def test_judgment_steps_never_evidence_checked(self, tmp_path):
        """Judgment steps (review, forage, etc.) are never reset by reconciliation."""
        from work_end_orchestrator import _reconcile
        progress, corrections = _reconcile(tmp_path, tmp_path / "project",
                                            {"review": "done", "forage": "done"}, "closing:verified")
        assert progress.get("review") == "done"
        assert progress.get("forage") == "done"
        assert len(corrections) == 0

    def test_corrects_false_land_done(self, tmp_path):
        """land=done but no .execute-progress → corrected."""
        from work_end_orchestrator import _reconcile
        progress, corrections = _reconcile(tmp_path, tmp_path / "project",
                                            {"land": "done"}, "closing:stamped")
        assert "land" not in progress
        assert "land" in corrections

    def test_preserves_valid_land_done(self, tmp_path):
        """land=done and .execute-progress exists → preserved."""
        (tmp_path / ".execute-progress").write_text("project:main=stamped\n")
        from work_end_orchestrator import _reconcile
        progress, corrections = _reconcile(tmp_path, tmp_path / "project",
                                            {"land": "done"}, "closing:stamped")
        assert progress.get("land") == "done"

    def test_skips_report_steps(self, tmp_path):
        """report_* steps are never evidence-checked — always preserved."""
        from work_end_orchestrator import _reconcile
        progress, corrections = _reconcile(tmp_path, tmp_path / "project",
                                            {"report_promote": "done"}, "closing:promoted")
        assert progress.get("report_promote") == "done"
        assert "report_promote" not in corrections

    def test_skips_attempt_keys(self, tmp_path):
        """_attempt keys are metadata, not steps — preserved."""
        from work_end_orchestrator import _reconcile
        progress, corrections = _reconcile(tmp_path, tmp_path / "project",
                                            {"review_attempt": "2"}, "closing:review")
        assert progress.get("review_attempt") == "2"

    def test_reconciliation_runs_on_orchestrator_start(self, tmp_path, monkeypatch):
        """Orchestrator calls _reconcile on startup — resets false mechanical progress."""
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "")
        update_close_progress(tmp_path, "land", "done")
        def mock_run(cmd, workspace, **kw):
            return {}
        monkeypatch.setattr("work_end_orchestrator._run_script", mock_run)
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:promoted",
        })
        assert result["ACTION"] == "trajectory"


class TestMechanicalRetry:
    """Mechanical steps retry up to 3 times before escalating to user."""

    def test_first_error_returns_retry_hint(self, tmp_path, monkeypatch):
        def fail_once(cmd, ws, **kw):
            return {"ERROR": "push_failed", "ERROR_DETAIL": "remote rejected"}
        monkeypatch.setattr("work_end_orchestrator._run_script", fail_once)
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "report_init", "done")
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "")
        update_close_progress(tmp_path, "review_pass", "done")
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "test", "base_branch": "main",
            "meta_state": "closing:verified",
        })
        assert result["ACTION"] == "error"
        assert result.get("RETRY") == "1"

    def test_third_error_escalates_to_user_input(self, tmp_path, monkeypatch):
        def fail_always(cmd, ws, **kw):
            return {"ERROR": "push_failed"}
        monkeypatch.setattr("work_end_orchestrator._run_script", fail_always)
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "report_init", "done")
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "")
        update_close_progress(tmp_path, "review_pass", "done")
        update_close_progress(tmp_path, "promote_mechanical_attempt", "2")
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "test", "base_branch": "main",
            "meta_state": "closing:verified",
        })
        assert result["ACTION"] == "user_input"
        assert result["CONTEXT"] == "step_failed"
        assert result["STEP"] == "promote"


class TestEvidenceChecks:
    """Evidence checks verify real state, not just trust progress."""

    def test_rebase_check_uses_git(self, tmp_path):
        from work_end_orchestrator import _check_rebase
        result = _check_rebase(tmp_path, tmp_path / "project")
        assert isinstance(result, bool)

    def test_checkout_main_check_uses_git(self, tmp_path):
        from work_end_orchestrator import _check_checkout_main
        result = _check_checkout_main(tmp_path, tmp_path / "project")
        assert isinstance(result, bool)

    def test_cleanup_check_verifies_journal_removed(self, tmp_path):
        from work_end_orchestrator import EVIDENCE_CHECKS
        (tmp_path / "JOURNAL.md").write_text("# Journal\n")
        check = EVIDENCE_CHECKS["cleanup"]
        assert check(tmp_path, tmp_path / "project") is False

    def test_cleanup_check_passes_when_plan_exists(self, tmp_path):
        from work_end_orchestrator import EVIDENCE_CHECKS
        (tmp_path / "JOURNAL.md").write_text("# Journal\n")
        (tmp_path / ".plan").write_text("state: drained\n")
        check = EVIDENCE_CHECKS["cleanup"]
        assert check(tmp_path, tmp_path / "project") is True


class TestAbortExtended:
    """Abort cleans up .execute-progress."""

    def test_abort_deletes_execute_progress(self, tmp_path):
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        (tmp_path / ".execute-progress").write_text("step1=done\n")

        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "abort": "yes",
        })
        assert result["ACTION"] == "complete"
        assert not (tmp_path / ".execute-progress").exists()
        assert not (tmp_path / ".close-progress").exists()


class TestCloseReportIntegration:
    """Close report records steps and renders summary."""

    REPORT_SCRIPT = Path(__file__).parent.parent / "work-end" / "close_report.py"

    def _report_run(self, args):
        return subprocess.run(
            [sys.executable, str(self.REPORT_SCRIPT)] + args,
            capture_output=True, text=True,
        )

    def test_full_report_lifecycle(self, tmp_path):
        """Init → record orchestrator steps → render produces summary."""
        rp = tmp_path / "report.json"

        result = self._report_run(["init", str(rp)])
        assert result.returncode == 0
        assert rp.exists()

        self._report_run(["record", str(rp), "step=promote", "result=ok",
                          "promoted_files=2", "target_repos=workspace"])
        self._report_run(["record", str(rp), "step=rebase", "result=ok",
                          "branch=issue-271", "base=main"])
        self._report_run(["record", str(rp), "step=squash", "result=ok",
                          "before=5", "after=2", "strategy=C"])
        self._report_run(["record", str(rp), "step=land", "result=ok",
                          "landed_sha=abc1234567890", "pushed_repos=project"])
        self._report_run(["record", str(rp), "step=close-issues", "result=ok",
                          "closed=1"])
        self._report_run(["record", str(rp), "step=verify", "result=ok",
                          "verified=pass"])
        self._report_run(["record", str(rp), "step=scaffold-cleanup", "result=ok"])

        result = self._report_run(["render", str(rp)])
        assert result.returncode == 0
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        assert len(lines) == 7
        assert all(l.startswith("✅") for l in lines)
        assert "Artifacts promoted" in lines[0]
        assert "Rebased" in lines[1]
        assert "Landed" in lines[3]
        assert "Verified" in lines[5]

    def test_report_with_failure(self, tmp_path):
        """Report renders failure icon for failed steps."""
        rp = tmp_path / "report.json"
        self._report_run(["init", str(rp)])
        self._report_run(["record", str(rp), "step=verify", "result=failed",
                          "verified=fail"])
        result = self._report_run(["render", str(rp)])
        assert "❌" in result.stdout
        assert "Verified" in result.stdout
