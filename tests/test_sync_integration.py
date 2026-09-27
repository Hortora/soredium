"""Integration test for sync mode orchestrator — full sequence walk-through."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from work_end_orchestrator import run_orchestrator, STEPS
from close_progress import update_close_progress


def _disable_postconditions(monkeypatch):
    for step in STEPS:
        if step.postcondition_fn is not None:
            monkeypatch.setattr(step, "postcondition_fn", None)
        if step.verify_fn is not None:
            monkeypatch.setattr(step, "verify_fn", None)


def _mock_scripts(monkeypatch):
    def mock_run(cmd, workspace, **kw):
        return {"REBASED": "yes", "LANDED": "yes", "LANDED_SHA": "abc123",
                "CLOSED": "1", "VERIFIED": "yes", "SWITCHED": "yes",
                "CLEANED": "yes", "WORKSPACE_PROMOTED": "0", "PROJECT_PROMOTED": "0"}
    monkeypatch.setattr("work_end_orchestrator._run_script", mock_run)


class TestSyncFullSequence:
    def _setup(self, tmp_path):
        ws = tmp_path
        plan = ws / ".plan"
        plan.write_text(
            "# Work Plan\n\n## State\n"
            "branch: test-branch\nstate: closing:review\ncovers: 1\n\n"
            "## Queue\n- [ ] test#1 — Test\n"
        )
        return ws, plan

    def _call(self, tmp_path, mode="sync", **extra):
        args = {
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "test-branch",
            "base_branch": "main",
            "meta_state": "closing:review",
            "mode": mode,
            "on_main": "no",
            "in_slot": "no",
            "covers": "1",
            "issue_repo": "test/repo",
            "plan_path": str(tmp_path / ".plan"),
            "dry_run": "yes",
        }
        args.update(extra)
        return run_orchestrator(args)

    def _complete(self, tmp_path, step):
        update_close_progress(tmp_path, step, "done")

    def test_sync_full_sequence(self, tmp_path, monkeypatch):
        """Walk through the complete sync sequence — no stamp, no cleanup."""
        ws, plan = self._setup(tmp_path)
        _mock_scripts(monkeypatch)
        _disable_postconditions(monkeypatch)

        actions_seen = []

        # Review phase (same as work-end)
        result = self._call(tmp_path)
        assert result["ACTION"] == "code_review"
        actions_seen.append("code_review")
        self._complete(tmp_path, "code_review")

        for dim in ["conformance", "coherence", "structure", "robustness"]:
            step = f"branch_audit_{dim}"
            result = self._call(tmp_path)
            assert result["ACTION"] == step
            actions_seen.append(step)
            self._complete(tmp_path, step)

        result = self._call(tmp_path)
        assert result["ACTION"] == "loose_ends"
        self._complete(tmp_path, "loose_ends")

        result = self._call(tmp_path)
        assert result["ACTION"] == "forcing_function"
        self._complete(tmp_path, "forcing_function")

        result = self._call(tmp_path)
        assert result["ACTION"] == "sweep_config"
        self._complete(tmp_path, "sweep_config")

        result = self._call(tmp_path, sweep_selected="")
        # No sweep items selected — skip straight to review_pass
        # review_pass is a lifecycle step — runs mechanically
        actions_seen.append("review_pass")

        # Walk through mechanical steps until we hit judgment or complete
        seen_sync_pass = False
        for _ in range(50):
            result = self._call(tmp_path)
            action = result.get("ACTION", "")
            actions_seen.append(action)

            if action == "complete":
                break
            elif action == "sync_pass":
                seen_sync_pass = True
                self._complete(tmp_path, "sync_pass")
            elif action in ("trajectory", "squash"):
                self._complete(tmp_path, action)
            elif action == "error":
                break
            # Mechanical steps auto-complete

        # Verify sync-specific assertions
        assert "stamp_pass" not in actions_seen, "stamp_pass should not run in sync mode"
        assert "checkout_main" not in actions_seen, "checkout_main should not run in sync mode"
        assert "cleanup_pass" not in actions_seen, "cleanup_pass should not run in sync mode"
        assert "cleanup_main" not in actions_seen, "cleanup_main should not run in sync mode"
        assert "arc42_scan" not in actions_seen, "arc42_scan should not run in sync mode"

    def test_end_mode_stamp_pass_not_skipped(self, tmp_path):
        """End mode: stamp_pass skip_fn returns False (not skipped).

        This validates that the sync skip predicate doesn't accidentally
        skip stamp_pass in end mode. The full end-mode sequence is tested
        in test_work_end_orchestrator.py — this test only confirms that
        sync changes didn't break the skip logic.
        """
        from work_end_orchestrator import OrchestratorContext
        ctx = OrchestratorContext(
            workspace=tmp_path, project=tmp_path,
            branch="test-branch", base_branch="main",
            meta_state="closing:merged", on_main=False,
            in_slot=False, covers="1", issue_repo="test/repo",
            progress={}, mode="end",
        )
        stamp = next(s for s in STEPS if s.name == "stamp_pass")
        sync = next(s for s in STEPS if s.name == "sync_pass")
        assert stamp.skip_fn(ctx) is False, "stamp_pass should NOT be skipped in end mode"
        assert sync.skip_fn(ctx) is True, "sync_pass should be skipped in end mode"
