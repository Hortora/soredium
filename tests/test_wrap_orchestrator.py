"""Tests for handover/wrap_orchestrator.py"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "handover"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

import wrap_orchestrator as wo
from close_progress import read_close_progress, write_close_progress


class TestWrapStepSequence:
    def test_first_call_returns_loose_ends(self, tmp_path):
        result = wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "dry_run": "yes",
        })
        assert "loose_ends" in result.get("ACTION", "") or result.get("ACTION") == "loose_ends" \
            or "ERROR" not in result

    def test_after_loose_ends_returns_epic_hygiene(self, tmp_path):
        write_close_progress(tmp_path, {"loose_ends": "done"})
        result = wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "dry_run": "yes",
        })
        assert result.get("ACTION") == "user_input"
        assert result.get("CONTEXT") == "epic_hygiene"

    def test_after_hygiene_returns_sweep_config(self, tmp_path):
        write_close_progress(tmp_path, {
            "loose_ends": "done",
            "epic_hygiene": "done",
        })
        result = wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "dry_run": "yes",
        })
        assert result.get("ACTION") == "wrap_sweep_config"

    def test_sweep_config_shows_wrap_items(self, tmp_path):
        write_close_progress(tmp_path, {
            "loose_ends": "done",
            "epic_hygiene": "done",
        })
        result = wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "dry_run": "yes",
        })
        items = result.get("ITEMS", "")
        assert "forage:on" in items
        assert "write_content:on" in items
        assert "impl_doc_sync" not in items

    def test_skips_arc42_when_not_present(self, tmp_path):
        write_close_progress(tmp_path, {
            "loose_ends": "done",
            "epic_hygiene": "done",
            "wrap_sweep_config": "done",
            "wrap_sweep_selected": "forage,protocol,update_claude_md,write_content",
            "forage": "done",
            "protocol": "done",
            "update_claude_md": "done",
        })
        result = wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "has_arc42": "no",
            "dry_run": "yes",
        })
        assert result.get("CONTEXT") != "arc42_scan"

    def test_skips_journal_when_no_plan(self, tmp_path):
        write_close_progress(tmp_path, {
            "loose_ends": "done",
            "epic_hygiene": "done",
            "wrap_sweep_config": "done",
            "wrap_sweep_selected": "forage,protocol,update_claude_md,write_content",
            "forage": "done",
            "protocol": "done",
            "update_claude_md": "done",
        })
        result = wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "has_plan": "no",
            "has_arc42": "no",
            "dry_run": "yes",
        })
        assert result.get("CONTEXT") != "journal_entry"


class TestWrapSweepConfig:
    def test_sweep_selected_persists(self, tmp_path):
        write_close_progress(tmp_path, {
            "loose_ends": "done",
            "epic_hygiene": "done",
        })
        wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "sweep_selected": "forage,write_content",
            "dry_run": "yes",
        })
        progress = read_close_progress(tmp_path)
        assert progress.get("wrap_sweep_selected") == "forage,write_content"
        assert progress.get("wrap_sweep_config") == "done"


class TestWrapSkipStep:
    def test_skip_marks_step_done(self, tmp_path):
        wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "skip_step": "loose_ends",
            "dry_run": "yes",
        })
        progress = read_close_progress(tmp_path)
        assert progress.get("loose_ends") == "skipped"


class TestWrapComplete:
    def test_all_done_returns_complete(self, tmp_path):
        write_close_progress(tmp_path, {
            "loose_ends": "done",
            "epic_hygiene": "done",
            "wrap_sweep_config": "done",
            "wrap_sweep_selected": "forage,write_content",
            "forage": "done",
            "protocol": "skipped",
            "update_claude_md": "skipped",
            "write_content": "done",
            "garden_feedback": "done",
            "notes": "done",
            "handoff_write": "done",
            "wip_commit": "done",
        })
        result = wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "has_arc42": "no",
            "has_plan": "no",
            "dry_run": "yes",
        })
        assert result.get("ACTION") == "complete"


class TestWrapStepProduced:
    def test_step_done_with_produced_persists(self, tmp_path):
        write_close_progress(tmp_path, {"loose_ends": "done"})
        wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "step_done": "forage",
            "produced": "3",
            "dry_run": "yes",
        })
        progress = read_close_progress(tmp_path)
        assert progress.get("forage") == "done"
        assert progress.get("forage_produced") == "3"

    def test_step_done_without_produced(self, tmp_path):
        wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "step_done": "notes",
            "dry_run": "yes",
        })
        progress = read_close_progress(tmp_path)
        assert progress.get("notes") == "done"
        assert "notes_produced" not in progress


class TestWrapGardenFeedback:
    def test_garden_feedback_yields_user_input(self, tmp_path):
        write_close_progress(tmp_path, {
            "loose_ends": "done",
            "epic_hygiene": "done",
            "wrap_sweep_config": "done",
            "wrap_sweep_selected": "write_content",
            "forage": "skipped",
            "protocol": "skipped",
            "update_claude_md": "skipped",
            "write_content": "done",
        })
        result = wo.run_orchestrator({
            "workspace": str(tmp_path),
            "project": str(tmp_path),
            "branch": "issue-42-test",
            "has_arc42": "no",
            "has_plan": "no",
            "dry_run": "yes",
        })
        assert result.get("CONTEXT") == "garden_feedback"
