"""Tests for work-end/progress_summary.py — mechanical step-status report."""

import sys
from pathlib import Path

import pytest

_work_end = Path(__file__).resolve().parent.parent / "work-end"
sys.path.insert(0, str(_work_end))

from progress_summary import format_summary


class TestCloseSummary:
    def test_all_done(self):
        progress = {
            "review": "done",
            "sweep_config": "done",
            "sweep_selected": "forage,protocol",
            "forage": "done",
            "forage_produced": "2",
            "protocol": "done",
            "update_claude_md": "skipped",
            "impl_doc_sync": "skipped",
            "adr": "skipped",
            "write_content": "skipped",
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
        assert "✅ Review" in output
        assert "✅ Forage SWEEP" in output
        assert "2 produced" in output
        assert "⏭ update-claude-md" not in output
        assert "⏭ CLAUDE.md sync" in output
        assert "deselected" in output

    def test_empty_progress(self):
        output = format_summary({}, "close")
        assert "Close summary" in output
        assert "not reached" in output

    def test_sweep_config_shows_selections(self):
        progress = {
            "review": "done",
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


class TestWrapSummary:
    def test_wrap_mode(self):
        progress = {
            "loose_ends": "done",
            "epic_hygiene": "done",
            "wrap_sweep_config": "done",
            "wrap_sweep_selected": "forage,protocol,update_claude_md,write_content",
            "forage": "done",
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
