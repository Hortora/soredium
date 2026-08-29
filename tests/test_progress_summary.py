"""Tests for work-end/progress_summary.py — mechanical step-status report."""

import json
import sys
from pathlib import Path

import pytest

_work_end = Path(__file__).resolve().parent.parent / "work-end"
sys.path.insert(0, str(_work_end))

from progress_summary import format_summary


class TestTableFormat:
    def test_renders_bordered_table(self):
        progress = {"code_review": "done"}
        output = format_summary(progress, "close")
        assert "┌" in output
        assert "┘" in output
        assert "│" in output
        assert "Step" in output
        assert "Status" in output
        assert "Result" in output

    def test_done_shows_done_status(self):
        progress = {"code_review": "done", "code_review_produced": "0"}
        output = format_summary(progress, "close")
        lines = output.split("\n")
        cr_line = [l for l in lines if "Code review" in l][0]
        assert "│ done" in cr_line

    def test_skipped_shows_skipped_status(self):
        progress = {"protocol": "skipped", "sweep_config": "done", "sweep_selected": "forage"}
        output = format_summary(progress, "close")
        lines = output.split("\n")
        proto_line = [l for l in lines if "Protocol" in l][0]
        assert "│ skipped" in proto_line

    def test_pending_shows_pending_status(self):
        progress = {}
        output = format_summary(progress, "close")
        lines = output.split("\n")
        cr_line = [l for l in lines if "Code review" in l][0]
        assert "│ pending" in cr_line


class TestCloseSummary:
    def test_review_sub_steps_shown(self):
        progress = {
            "code_review": "done",
            "code_review_produced": "2",
            "branch_audit_conformance": "done",
            "branch_audit_coherence": "done",
            "branch_audit_structure": "done",
            "branch_audit_robustness": "done",
            "loose_ends": "done",
            "forcing_function": "done",
            "sweep_config": "done",
            "sweep_selected": "forage,write_content",
            "forage": "done",
            "forage_produced": "2",
            "write_content": "done",
            "protocol": "skipped",
            "update_claude_md": "skipped",
            "impl_doc_sync": "skipped",
            "adr": "skipped",
            "promote": "done",
            "trajectory": "done",
            "rebase": "done",
            "squash": "done",
            "land": "done",
            "close_issues": "done",
            "verify": "done",
            "arc42_scan": "done",
            "session_rename": "skipped",
            "garden_feedback": "done",
            "notes": "skipped",
        }
        output = format_summary(progress, "close")
        assert "Code review" in output
        assert "Conformance" in output
        assert "Coherence" in output
        assert "Structure" in output
        assert "Robustness" in output
        assert "Loose ends" in output
        assert "Forcing function" in output
        assert "Forage SWEEP" in output
        assert "2 produced" in output
        lines = output.split("\n")
        claude_line = [l for l in lines if "CLAUDE.md sync" in l][0]
        assert "deselected" in claude_line

    def test_empty_progress(self):
        output = format_summary({}, "close")
        assert "Step" in output
        assert "pending" in output

    def test_sweep_config_shows_selections(self):
        progress = {
            "code_review": "done",
            "sweep_config": "done",
            "sweep_selected": "forage,write_content",
        }
        output = format_summary(progress, "close")
        assert "forage, write_content" in output

    def test_deselected_shows_correctly(self):
        progress = {
            "sweep_config": "done",
            "sweep_selected": "forage",
            "forage": "done",
            "protocol": "skipped",
            "update_claude_md": "skipped",
        }
        output = format_summary(progress, "close")
        lines = output.split("\n")
        protocol_line = [l for l in lines if "Protocol" in l][0]
        assert "deselected" in protocol_line

    def test_not_configured_when_sweep_selected_missing(self):
        progress = {
            "sweep_config": "done",
            "forage": "skipped",
        }
        output = format_summary(progress, "close")
        lines = output.split("\n")
        forage_line = [l for l in lines if "Forage" in l][0]
        assert "not configured" in forage_line

    def test_findings_shown_when_workspace_provided(self, tmp_path):
        audit_dir = tmp_path / ".audit"
        audit_dir.mkdir()
        findings = [
            {"severity": "warning", "source": "code-review", "detail": "Unchecked error",
             "status": "resolved", "resolution": "abc1234", "check": "error-handling",
             "location": "auth.py:42", "branch": "test"},
            {"severity": "note", "source": "branch-audit", "dimension": "conformance",
             "detail": "Missing spec item", "status": "filed", "resolution": "#123",
             "check": "spec-gap", "branch": "test"},
        ]
        (audit_dir / "findings.jsonl").write_text(
            "\n".join(json.dumps(f) for f in findings) + "\n"
        )
        progress = {
            "code_review": "done",
            "forcing_function": "done",
        }
        output = format_summary(progress, "close", workspace=tmp_path)
        assert "Findings:" in output
        assert "code-review" in output
        assert "Unchecked error" in output
        assert "branch-audit" in output

    def test_dimension_finding_counts(self, tmp_path):
        audit_dir = tmp_path / ".audit"
        audit_dir.mkdir()
        findings = [
            {"source": "branch-audit", "dimension": "conformance", "detail": "gap1",
             "status": "open", "check": "c1", "branch": "t"},
            {"source": "branch-audit", "dimension": "conformance", "detail": "gap2",
             "status": "open", "check": "c2", "branch": "t"},
            {"source": "branch-audit", "dimension": "structure", "detail": "boundary",
             "status": "open", "check": "s1", "branch": "t"},
        ]
        (audit_dir / "findings.jsonl").write_text(
            "\n".join(json.dumps(f) for f in findings) + "\n"
        )
        progress = {
            "branch_audit_conformance": "done",
            "branch_audit_structure": "done",
            "branch_audit_coherence": "done",
            "branch_audit_robustness": "done",
        }
        output = format_summary(progress, "close", workspace=tmp_path)
        lines = output.split("\n")
        conf_line = [l for l in lines if "Conformance" in l][0]
        assert "2 findings" in conf_line
        struct_line = [l for l in lines if "Structure" in l][0]
        assert "1 finding" in struct_line
        coh_line = [l for l in lines if "Coherence" in l][0]
        assert "clean" in coh_line


class TestWrapSummary:
    def test_wrap_mode(self):
        progress = {
            "loose_ends": "done",
            "epic_hygiene": "done",
            "wrap_sweep_config": "done",
            "wrap_sweep_selected": "forage,protocol,update_claude_md,write_content",
            "forage": "done",
            "forage_produced": "2",
            "protocol": "done",
            "update_claude_md": "done",
            "write_content": "done",
            "garden_feedback": "skipped",
            "notes": "skipped",
            "handoff_write": "done",
            "wip_commit": "done",
        }
        output = format_summary(progress, "wrap")
        assert "Loose ends" in output
        assert "HANDOFF.md" in output
        lines = output.split("\n")
        gf_line = [l for l in lines if "Garden feedback" in l][0]
        assert "skipped" in gf_line

    def test_wrap_deselected(self):
        progress = {
            "wrap_sweep_config": "done",
            "wrap_sweep_selected": "forage",
            "forage": "done",
            "write_content": "skipped",
        }
        output = format_summary(progress, "wrap")
        lines = output.split("\n")
        write_line = [l for l in lines if "Diary" in l][0]
        assert "deselected" in write_line


class TestRetryAndPerRepo:
    def test_retry_count_shown(self):
        progress = {
            "promote": "done",
            "promote_mechanical_attempt": "2",
        }
        output = format_summary(progress, "close")
        lines = output.split("\n")
        promote_line = [l for l in lines if "Promote" in l][0]
        assert "2 retries" in promote_line

    def test_per_repo_breakdown_shown(self):
        progress = {
            "rebase:engine": "done",
            "rebase:blocks": "done",
            "rebase:qhorus": "skipped",
        }
        output = format_summary(progress, "close")
        lines = output.split("\n")
        rebase_line = [l for l in lines if "Rebase" in l][0]
        assert "engine:done" in rebase_line
        assert "blocks:done" in rebase_line
        assert "qhorus:skipped" in rebase_line

    def test_per_repo_all_done_shows_done_status(self):
        progress = {
            "promote:engine": "done",
            "promote:blocks": "done",
        }
        output = format_summary(progress, "close")
        lines = output.split("\n")
        promote_line = [l for l in lines if "Promote" in l][0]
        assert "│ done" in promote_line

    def test_per_repo_partial_shows_partial_status(self):
        progress = {
            "rebase:engine": "done",
            "rebase:blocks": "skipped",
        }
        output = format_summary(progress, "close")
        lines = output.split("\n")
        rebase_line = [l for l in lines if "Rebase" in l][0]
        assert "│ partial" in rebase_line


class TestIncidents:
    def test_step_error_shown(self, tmp_path):
        log = [{"ts": "2026-08-29T10:00:00", "action": "step-error",
                "step": "promote", "error": "push_failed", "retry": "1"}]
        (tmp_path / ".close-log.jsonl").write_text(
            "\n".join(json.dumps(e) for e in log) + "\n"
        )
        output = format_summary({"promote": "done"}, "close", workspace=tmp_path)
        assert "Incidents:" in output
        assert "promote" in output
        assert "push_failed" in output

    def test_stale_reset_shown(self, tmp_path):
        log = [{"ts": "2026-08-29T10:00:00", "action": "stale-progress-reset",
                "step": "", "error": ""}]
        (tmp_path / ".close-log.jsonl").write_text(json.dumps(log[0]) + "\n")
        output = format_summary({}, "close", workspace=tmp_path)
        assert "progress reset (stale)" in output

    def test_reconciliation_shown(self, tmp_path):
        log = [{"ts": "2026-08-29T10:00:00", "action": "reconciliation-correction",
                "step": "", "error": "", "corrected_steps": "land,verify"}]
        (tmp_path / ".close-log.jsonl").write_text(json.dumps(log[0]) + "\n")
        output = format_summary({}, "close", workspace=tmp_path)
        assert "reconciliation corrected" in output
        assert "land,verify" in output

    def test_step_failed_shown(self, tmp_path):
        log = [{"ts": "2026-08-29T10:00:00", "action": "step-failed",
                "step": "forage", "error": "", "attempts": "3",
                "reason": "timeout"}]
        (tmp_path / ".close-log.jsonl").write_text(json.dumps(log[0]) + "\n")
        output = format_summary({}, "close", workspace=tmp_path)
        assert "forage failed after 3 attempts" in output

    def test_no_incidents_no_section(self, tmp_path):
        log = [{"ts": "2026-08-29T10:00:00", "action": "complete",
                "step": "", "error": ""}]
        (tmp_path / ".close-log.jsonl").write_text(json.dumps(log[0]) + "\n")
        output = format_summary({"promote": "done"}, "close", workspace=tmp_path)
        assert "Incidents:" not in output

    def test_no_log_file_no_section(self, tmp_path):
        output = format_summary({"promote": "done"}, "close", workspace=tmp_path)
        assert "Incidents:" not in output


class TestLegacyReviewMigration:
    def test_legacy_review_done_not_in_close_summary(self):
        """Legacy 'review=done' should not appear as a visible step."""
        progress = {"review": "done"}
        output = format_summary(progress, "close")
        lines = output.split("\n")
        step_lines = [l for l in lines if "│" in l and "Step" not in l]
        for line in step_lines:
            if "Review" in line:
                assert "Code review" in line
