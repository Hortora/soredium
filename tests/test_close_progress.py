"""Tests for work-end/close_progress.py"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

from close_progress import (
    read_close_progress,
    write_close_progress,
    update_close_progress,
    delete_close_progress,
    is_stale,
)


class TestReadWrite:

    def test_read_empty(self, tmp_path):
        result = read_close_progress(tmp_path)
        assert result == {}

    def test_write_and_read_roundtrip(self, tmp_path):
        entries = {"review": "done", "sweep_config": "done"}
        write_close_progress(tmp_path, entries)
        result = read_close_progress(tmp_path)
        assert result == entries

    def test_update_adds_key(self, tmp_path):
        update_close_progress(tmp_path, "review", "done")
        result = read_close_progress(tmp_path)
        assert result["review"] == "done"

    def test_update_overwrites_key(self, tmp_path):
        update_close_progress(tmp_path, "review", "pending")
        update_close_progress(tmp_path, "review", "done")
        result = read_close_progress(tmp_path)
        assert result["review"] == "done"

    def test_update_preserves_existing_keys(self, tmp_path):
        update_close_progress(tmp_path, "review", "done")
        update_close_progress(tmp_path, "forage", "done")
        result = read_close_progress(tmp_path)
        assert result["review"] == "done"
        assert result["forage"] == "done"


class TestAtomicWrite:

    def test_no_tmp_left(self, tmp_path):
        write_close_progress(tmp_path, {"review": "done"})
        assert not (tmp_path / ".close-progress.tmp").exists()

    def test_survives_crash(self, tmp_path):
        write_close_progress(tmp_path, {"review": "done"})
        with patch("os.replace", side_effect=OSError("crash")):
            with pytest.raises(OSError):
                update_close_progress(tmp_path, "forage", "done")
        result = read_close_progress(tmp_path)
        assert result == {"review": "done"}
        assert "forage" not in result


class TestDelete:

    def test_delete(self, tmp_path):
        write_close_progress(tmp_path, {"review": "done"})
        delete_close_progress(tmp_path)
        assert read_close_progress(tmp_path) == {}

    def test_delete_removes_tmp(self, tmp_path):
        tmp_file = tmp_path / ".close-progress.tmp"
        tmp_file.write_text("stale")
        delete_close_progress(tmp_path)
        assert not tmp_file.exists()

    def test_delete_nonexistent_is_safe(self, tmp_path):
        delete_close_progress(tmp_path)


class TestIsStale:

    def test_empty_progress_not_stale(self):
        assert is_stale({}, "closing:review") is False

    def test_progress_behind_meta_not_stale(self):
        progress = {"review": "done"}
        assert is_stale(progress, "closing:promoted") is False

    def test_progress_at_meta_not_stale(self):
        progress = {"review": "done"}
        assert is_stale(progress, "closing:review") is False

    def test_progress_ahead_of_meta_is_stale(self):
        progress = {"review": "done", "promote": "done", "land": "done"}
        assert is_stale(progress, "closing:review") is True

    def test_unknown_meta_state_not_stale(self):
        progress = {"review": "done"}
        assert is_stale(progress, "some_unknown_state") is False

    def test_active_state_detects_stale_from_prior_close(self):
        progress = {"review": "done", "promote": "done"}
        assert is_stale(progress, "active") is True

    def test_drained_state_not_stale(self):
        progress = {"review": "done"}
        assert is_stale(progress, "drained") is False

    def test_not_stale_when_plan_state_matches_progress(self, tmp_path):
        """Regression: lifecycle transitions advance .plan but caller passes stale meta_state.
        is_stale must read .plan to get the actual state, not trust the argument."""
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: closing:promoted\nbranch: test\n")
        progress = {"review": "done", "promote": "done", "trajectory": "done"}
        assert is_stale(progress, "closing:review", plan_path=plan) is False

    def test_still_stale_when_plan_state_behind_progress(self, tmp_path):
        """Genuine stale: plan is active but progress has promoted-phase entries."""
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\nbranch: test\n")
        progress = {"review": "done", "promote": "done", "trajectory": "done"}
        assert is_stale(progress, "active", plan_path=plan) is True

    def test_stale_without_plan_path_uses_meta_state(self):
        """Backward compat: no plan_path means trust meta_state argument."""
        progress = {"review": "done", "promote": "done", "land": "done"}
        assert is_stale(progress, "closing:review") is True

    def test_per_repo_keys_resolve_to_base_step_phase(self):
        """#332: rebase:engine should map to rebase (closing:promoted), not default."""
        progress = {
            "trajectory": "done",
            "rebase:work": "done",
            "rebase:engine": "done",
            "_branch": "issue-238-test",
        }
        assert is_stale(progress, "closing:promoted") is False

    def test_per_repo_keys_detect_genuine_staleness(self):
        """#332: per-repo keys from a later phase should still detect staleness."""
        progress = {
            "close_issues:work": "done",
            "close_issues:engine": "done",
        }
        assert is_stale(progress, "closing:promoted") is True

    def test_metadata_keys_ignored(self):
        """#332: _branch, last_yielded, sweep_selected are metadata, not steps."""
        progress = {
            "trajectory": "done",
            "_branch": "issue-238-test",
            "last_yielded": "squash",
            "sweep_selected": "forage,protocol",
        }
        assert is_stale(progress, "closing:promoted") is False

    def test_not_stale_when_stamped_progress_and_branch_landed(self):
        """Work landed on main — progress with stamped-phase steps is not stale
        even if meta_state regressed to active/idle."""
        progress = {
            "review": "done", "promote": "done", "land": "done",
            "verify": "done", "checkout_main": "done",
        }
        project = Path("/fake/project")
        landed = MagicMock(return_value=True)
        is_stale.__globals__["_branch_landed_on_main"] = landed
        try:
            assert is_stale(progress, "active", project=project, branch="feat-x") is False
            landed.assert_called_once_with(project, "feat-x")
        finally:
            from close_progress import _branch_landed_on_main
            is_stale.__globals__["_branch_landed_on_main"] = _branch_landed_on_main

    def test_still_stale_when_stamped_progress_but_not_landed(self):
        """Progress ahead of meta and branch NOT on main — genuinely stale."""
        progress = {
            "review": "done", "promote": "done", "land": "done",
            "verify": "done", "checkout_main": "done",
        }
        project = Path("/fake/project")
        landed = MagicMock(return_value=False)
        is_stale.__globals__["_branch_landed_on_main"] = landed
        try:
            assert is_stale(progress, "active", project=project, branch="feat-x") is True
        finally:
            from close_progress import _branch_landed_on_main
            is_stale.__globals__["_branch_landed_on_main"] = _branch_landed_on_main

    def test_evidence_gate_not_checked_for_non_stamped_progress(self):
        """If max progress phase is below closing:stamped, skip evidence check —
        the work hasn't reached the landing stage yet."""
        progress = {"review": "done", "promote": "done"}
        assert is_stale(progress, "closing:review", project=Path("/x"), branch="b") is True

    def test_evidence_gate_skipped_without_project_or_branch(self):
        """Backward compat: no project/branch means skip evidence check."""
        progress = {
            "review": "done", "promote": "done", "land": "done",
            "verify": "done", "checkout_main": "done",
        }
        assert is_stale(progress, "active") is True

    def test_not_stale_when_review_gates_passed(self):
        """#398: progress with completed review gates should never be wiped,
        even if .plan is missing and meta_state regressed."""
        progress = {
            "code_review": "done",
            "branch_audit_conformance": "done",
            "branch_audit_coherence": "done",
            "branch_audit_structure": "done",
            "branch_audit_robustness": "done",
            "loose_ends": "done",
            "forcing_function": "done",
            "sweep_config": "done",
        }
        assert is_stale(progress, "active") is False

    def test_still_stale_when_partial_review(self):
        """Only code_review done (not all audit dimensions) — genuinely stale."""
        progress = {"code_review": "done", "promote": "done"}
        assert is_stale(progress, "active") is True

    def test_not_stale_review_gate_with_skipped_steps(self):
        """Review gate steps marked 'skipped' still count as passed."""
        progress = {
            "code_review": "skipped",
            "branch_audit_conformance": "done",
            "branch_audit_coherence": "done",
            "branch_audit_structure": "skipped",
            "branch_audit_robustness": "done",
        }
        assert is_stale(progress, "active") is False

    def test_report_steps_excluded_from_staleness(self):
        """#403: report_init alone should not trigger staleness — it's bookkeeping."""
        progress = {"report_init": "done"}
        assert is_stale(progress, "active") is False

    def test_report_steps_with_substantive_still_detects(self):
        """report_* excluded but substantive steps still trigger staleness."""
        progress = {"report_init": "done", "promote": "done"}
        assert is_stale(progress, "active") is True
