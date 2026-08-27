"""Tests for work-end/close_resume.py — interrupted close detection."""

import sys
from pathlib import Path

import pytest

_work_end = Path(__file__).resolve().parent.parent / "work-end"
sys.path.insert(0, str(_work_end))

from close_resume import detect_resume, format_resume_prompt
from close_progress import update_close_progress


class TestDetectResume:
    def test_no_progress_file(self, tmp_path):
        result = detect_resume(tmp_path)
        assert result["INTERRUPTED"] == "no"

    def test_empty_progress(self, tmp_path):
        (tmp_path / ".close-progress").write_text("")
        result = detect_resume(tmp_path)
        assert result["INTERRUPTED"] == "no"

    def test_partial_progress_detected(self, tmp_path):
        update_close_progress(tmp_path, "_branch", "issue-42-test")
        update_close_progress(tmp_path, "code_review", "done")
        update_close_progress(tmp_path, "branch_audit_conformance", "done")
        update_close_progress(tmp_path, "branch_audit_coherence", "skipped")
        result = detect_resume(tmp_path)
        assert result["INTERRUPTED"] == "yes"
        assert result["COMPLETED"] == "3"
        assert result["NEXT_STEP"] == "branch_audit_structure"
        assert result["BRANCH"] == "issue-42-test"
        assert "code_review" in result["STEPS_DONE"]

    def test_all_done_not_interrupted(self, tmp_path):
        for step in ["code_review", "branch_audit_conformance",
                     "branch_audit_coherence", "branch_audit_structure",
                     "branch_audit_robustness", "loose_ends",
                     "forcing_function", "sweep_config", "forage",
                     "protocol", "update_claude_md", "impl_doc_sync",
                     "adr", "write_content", "promote", "trajectory",
                     "rebase", "squash", "land", "close_issues", "verify",
                     "arc42_scan", "session_rename", "garden_feedback", "notes"]:
            update_close_progress(tmp_path, step, "done")
        result = detect_resume(tmp_path)
        assert result["INTERRUPTED"] == "yes"
        assert result["REMAINING"] == "0"


class TestFormatResumePrompt:
    def test_not_interrupted(self):
        result = format_resume_prompt({"INTERRUPTED": "no"})
        assert result == ""

    def test_interrupted_shows_done_and_remaining(self, tmp_path):
        result = {
            "INTERRUPTED": "yes",
            "COMPLETED": "3",
            "REMAINING": "22",
            "NEXT_STEP": "branch_audit_structure",
            "BRANCH": "issue-42-test",
            "STEPS_DONE": "code_review,branch_audit_conformance,branch_audit_coherence",
            "STEPS_REMAINING": "branch_audit_structure,branch_audit_robustness",
        }
        prompt = format_resume_prompt(result)
        assert "issue-42-test" in prompt
        assert "Code review" in prompt
        assert "Structure audit" in prompt
        assert "Completed: 3" in prompt
