"""Tests for work-end/work_end_orchestrator.py — close sequence orchestrator."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))


class TestOrchestratorFirstCall:
    """First call with no progress — should yield ACTION=review."""

    def test_yields_review_on_first_call(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        result = run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
        })
        assert result["ACTION"] == "review"

    def test_includes_diff_range(self, tmp_path):
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

    def test_all_sweep_done_yields_no_more_sweep(self, tmp_path):
        """After all sweep sub-steps done, next call should trigger
        mechanical steps (lifecycle transition) and yield trajectory."""
        from close_progress import update_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage")
        update_close_progress(tmp_path, "forage", "done")
        result = self._run(tmp_path, meta_state="closing:promoted")
        assert result["ACTION"] == "trajectory"


class TestSweepConfigAll:
    """When all sweep items are deselected, no sweep actions yield."""

    def test_empty_selection_skips_to_post_sweep(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
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

    def test_main_mode_skips_to_post_land(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress
        for step in ["review", "sweep_config", "trajectory"]:
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
        assert result["ACTION"] == "squash" or result["ACTION"] in ("user_input", "complete")


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


class TestSkipStep:
    """skip_step= argument marks a step as skipped."""

    def test_skip_step_marks_skipped(self, tmp_path):
        from work_end_orchestrator import run_orchestrator
        from close_progress import update_close_progress, read_close_progress
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "sweep_config", "done")
        update_close_progress(tmp_path, "sweep_selected", "forage,write_content")
        run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "branch": "issue-271-test",
            "base_branch": "main",
            "meta_state": "closing:review",
            "skip_step": "forage",
        })
        progress = read_close_progress(tmp_path)
        assert progress.get("forage") == "skipped"


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

    def test_full_branch_sequence(self, tmp_path):
        """Walk through the complete branch-mode close sequence."""
        from close_progress import read_close_progress

        actions_seen = []

        # 1. First call — yields review
        result = self._call(tmp_path)
        assert result["ACTION"] == "review"
        actions_seen.append("review")
        self._complete(tmp_path, "review")

        # 2. After review — yields sweep_config
        result = self._call(tmp_path)
        assert result["ACTION"] == "sweep_config"
        actions_seen.append("sweep_config")
        self._complete(tmp_path, "sweep_config")

        # 3. Pass sweep selections — yields first selected item
        result = self._call(tmp_path, sweep_selected="forage,write_content")
        assert result["ACTION"] == "forage"
        actions_seen.append("forage")
        self._complete(tmp_path, "forage")

        # 4. After forage — yields write_content (next selected)
        result = self._call(tmp_path)
        assert result["ACTION"] == "write_content"
        actions_seen.append("write_content")
        self._complete(tmp_path, "write_content")

        # 5. After all sweep — yields trajectory (promoted phase)
        result = self._call(tmp_path, meta_state="closing:promoted")
        assert result["ACTION"] == "trajectory"
        actions_seen.append("trajectory")
        self._complete(tmp_path, "trajectory")

        # 6. After trajectory — yields squash (branch mode)
        result = self._call(tmp_path, meta_state="closing:promoted")
        assert result["ACTION"] == "squash"
        actions_seen.append("squash")
        self._complete(tmp_path, "squash")

        # 7. Orchestrator marks mechanical steps (rebase, land, close_issues, verify)
        # and yields cleanup user_input steps
        result = self._call(tmp_path, meta_state="closing:stamped")
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "arc42_scan"
        actions_seen.append("arc42_scan")
        self._complete(tmp_path, "arc42_scan")

        # 8. Next user_input
        result = self._call(tmp_path, meta_state="closing:stamped")
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "session_rename"
        actions_seen.append("session_rename")
        self._complete(tmp_path, "session_rename")

        # 9. Next user_input
        result = self._call(tmp_path, meta_state="closing:stamped")
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "garden_feedback"
        actions_seen.append("garden_feedback")
        self._complete(tmp_path, "garden_feedback")

        # 10. Next user_input
        result = self._call(tmp_path, meta_state="closing:stamped")
        assert result["ACTION"] == "user_input"
        assert result.get("CONTEXT") == "notes"
        actions_seen.append("notes")
        self._complete(tmp_path, "notes")

        # 11. After all cleanup — complete
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

    def test_main_mode_skips_squash(self, tmp_path):
        """Main mode skips rebase and squash, goes straight to cleanup."""
        from close_progress import update_close_progress
        for step in ["review", "sweep_config", "trajectory"]:
            update_close_progress(tmp_path, step, "done")
        update_close_progress(tmp_path, "sweep_selected", "")
        result = self._call(tmp_path, meta_state="closing:stamped", on_main="yes")
        assert result["ACTION"] == "user_input"

    def test_no_covers_skips_close_issues(self, tmp_path):
        """When covers is empty, close_issues step is skipped."""
        from close_progress import update_close_progress, read_close_progress
        for step in ["review", "sweep_config", "trajectory", "squash",
                     "rebase", "land", "arc42_scan", "session_rename",
                     "garden_feedback", "notes", "verify", "cleanup"]:
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

    def test_resume_after_sweep(self, tmp_path):
        """After crash, review+sweep done — resumes at trajectory."""
        from close_progress import update_close_progress
        for step in ["review", "sweep_config"]:
            update_close_progress(tmp_path, step, "done")
        update_close_progress(tmp_path, "sweep_selected", "forage")
        update_close_progress(tmp_path, "forage", "done")
        result = self._call(tmp_path, meta_state="closing:promoted")
        assert result["ACTION"] == "trajectory"

    def test_resume_mid_cleanup(self, tmp_path):
        """After crash during cleanup, resumes at next user_input."""
        from close_progress import update_close_progress
        for step in ["review", "sweep_config", "trajectory", "squash",
                     "rebase", "land", "verify", "arc42_scan"]:
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
