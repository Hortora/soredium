#!/usr/bin/env python3
"""Tests for project/conflict_resolution.py — three-tier conflict resolution."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


class TestClassifyConflict:
    def test_all_lifecycle_files(self):
        from conflict_resolution import classify_conflict
        auto, remaining = classify_conflict([
            ".plan", "JOURNAL.md", ".work-progress"])
        assert set(auto) == {".plan", "JOURNAL.md", ".work-progress"}
        assert remaining == []

    def test_mixed_files(self):
        from conflict_resolution import classify_conflict
        auto, remaining = classify_conflict([
            ".plan", "src/main.py", "JOURNAL.md"])
        assert set(auto) == {".plan", "JOURNAL.md"}
        assert remaining == ["src/main.py"]

    def test_no_lifecycle_files(self):
        from conflict_resolution import classify_conflict
        auto, remaining = classify_conflict(["src/main.py", "README.md"])
        assert auto == []
        assert remaining == ["src/main.py", "README.md"]

    def test_empty_list(self):
        from conflict_resolution import classify_conflict
        auto, remaining = classify_conflict([])
        assert auto == []
        assert remaining == []

    def test_close_progress_is_lifecycle(self):
        from conflict_resolution import classify_conflict
        auto, _ = classify_conflict([".close-progress"])
        assert ".close-progress" in auto

    def test_close_log_is_lifecycle(self):
        from conflict_resolution import classify_conflict
        auto, _ = classify_conflict([".close-log.jsonl"])
        assert ".close-log.jsonl" in auto

    def test_artifacts_promoted_is_lifecycle(self):
        from conflict_resolution import classify_conflict
        auto, _ = classify_conflict([".artifacts-promoted"])
        assert ".artifacts-promoted" in auto


class TestMakeRebaseErrorHandler:
    def test_non_rebase_error_passes_through(self):
        from conflict_resolution import make_rebase_error_handler
        handler = make_rebase_error_handler()
        result = handler(None, None, {"ERROR": "timeout"})
        assert result is None

    def test_all_lifecycle_auto_resolved(self):
        from conflict_resolution import make_rebase_error_handler
        handler = make_rebase_error_handler()
        result = handler(
            None, None,
            {"ERROR": "rebase_conflict",
             "CONFLICTED_FILES": ".plan,JOURNAL.md"})
        assert result is None

    def test_yields_for_source_conflicts(self):
        from conflict_resolution import make_rebase_error_handler
        handler = make_rebase_error_handler()
        result = handler(
            None, None,
            {"ERROR": "rebase_conflict",
             "CONFLICTED_FILES": ".plan,src/main.py"})
        assert result is not None
        assert result["ACTION"] == "resolve_conflict"
        assert "src/main.py" in result["FILES"]
        assert ".plan" in result["AUTO_RESOLVED"]

    def test_no_conflicted_files_passes_through(self):
        from conflict_resolution import make_rebase_error_handler
        handler = make_rebase_error_handler()
        result = handler(
            None, None,
            {"ERROR": "rebase_conflict", "CONFLICTED_FILES": ""})
        assert result is None

    def test_all_source_files_yield(self):
        from conflict_resolution import make_rebase_error_handler
        handler = make_rebase_error_handler()
        result = handler(
            None, None,
            {"ERROR": "rebase_conflict",
             "CONFLICTED_FILES": "src/a.py,src/b.py"})
        assert result is not None
        assert result["ACTION"] == "resolve_conflict"
        assert "src/a.py" in result["FILES"]
        assert "src/b.py" in result["FILES"]
        assert result.get("AUTO_RESOLVED", "") == ""


class TestLifecycleAutoResolveSet:
    def test_contains_expected_files(self):
        from conflict_resolution import LIFECYCLE_AUTO_RESOLVE
        expected = {".plan", "JOURNAL.md", ".close-progress", ".work-progress",
                    ".close-log.jsonl", ".artifacts-promoted"}
        assert expected.issubset(LIFECYCLE_AUTO_RESOLVE)
