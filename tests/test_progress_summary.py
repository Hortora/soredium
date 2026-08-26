"""Tests for work-end/progress_summary.py — mechanical step-status report."""

import json
import sys
from pathlib import Path

import pytest

_work_end = Path(__file__).resolve().parent.parent / "work-end"
sys.path.insert(0, str(_work_end))

from progress_summary import format_summary


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
        assert "Close summary" in output
        assert "✅ Code review" in output
        assert "✅ Conformance" in output
        assert "✅ Coherence" in output
        assert "✅ Structure" in output
        assert "✅ Robustness" in output
        assert "✅ Loose ends" in output
        assert "✅ Forcing function" in output
        assert "✅ Forage SWEEP" in output
        assert "2 produced" in output
        assert "⏭ CLAUDE.md sync" in output
        assert "deselected" in output

    def test_empty_progress(self):
        output = format_summary({}, "close")
        assert "Close summary" in output
        assert "not reached" in output

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
        assert "Wrap summary" in output
        assert "✅ Loose ends" in output
        assert "✅ HANDOFF.md" in output
        assert "⏭ Garden feedback" in output

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


class TestLegacyReviewMigration:
    def test_legacy_review_done_not_in_close_summary(self):
        """Legacy 'review=done' should not appear as a visible step."""
        progress = {"review": "done"}
        output = format_summary(progress, "close")
        lines = output.split("\n")
        step_lines = [l for l in lines if l.strip().startswith(("✅", "⏭", "⬜"))]
        for line in step_lines:
            assert "Review" not in line or "Code review" in line
