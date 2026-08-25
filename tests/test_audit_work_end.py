"""Tests for work-end/audit_work_end.py — dry-run audit of orchestrator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))


class TestAuditBranchMode:

    def test_branch_mode_completes(self, tmp_path):
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="branch")
        assert result["RESULT"] == "PASS", f"Missing: {result['steps_missing']}"
        assert result["fallback_triggers"] == 0

    def test_branch_mode_reaches_core_steps(self, tmp_path):
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="branch")
        for step in ["review", "sweep_config", "forage", "trajectory", "squash"]:
            assert step in result["steps_reached"], f"Missing core step: {step}"

    def test_branch_mode_reaches_mechanical_steps(self, tmp_path):
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="branch")
        for step in ["report_init", "promote", "rebase", "land",
                      "close_issues", "verify", "checkout_main", "cleanup"]:
            assert step in result["steps_reached"], f"Missing mechanical step: {step}"

    def test_branch_mode_reaches_lifecycle_steps(self, tmp_path):
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="branch")
        for step in ["review_pass", "promote_pass", "push_pass",
                      "merge_pass", "stamp_pass", "cleanup_pass"]:
            assert step in result["steps_reached"], f"Missing lifecycle step: {step}"


class TestAuditSlotMode:

    def test_slot_mode_completes(self, tmp_path):
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="slot")
        assert result["RESULT"] == "PASS", f"Missing: {result['steps_missing']}"

    def test_slot_mode_exercises_slot_routing(self, tmp_path):
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="slot")
        for step in ["write_marker", "archive_slot", "report_archive"]:
            assert step in result["steps_reached"], f"Missing slot step: {step}"

    def test_slot_mode_skips_branch_only_steps(self, tmp_path):
        """Slot mode should NOT skip checkout_main or cleanup_stack."""
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="slot")
        assert "checkout_main" in result["steps_reached"]


class TestAuditMainMode:

    def test_main_mode_completes(self, tmp_path):
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="main")
        assert result["RESULT"] == "PASS", f"Missing: {result['steps_missing']}"

    def test_main_mode_skips_branch_steps(self, tmp_path):
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="main")
        branch_only = ["rebase", "report_rebase", "squash", "report_squash",
                        "checkout_main", "cleanup_stack"]
        for step in branch_only:
            assert step not in result["steps_reached"], f"Main mode should skip: {step}"

    def test_main_mode_fires_cleanup_main(self, tmp_path):
        from audit_work_end import run_audit
        result = run_audit(tmp_path, mode="main")
        assert "cleanup_main" in result["steps_reached"]
        assert "cleanup_pass" not in result["steps_reached"]
