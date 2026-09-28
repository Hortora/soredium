#!/usr/bin/env python3
"""Tests for project/work_progress.py — unified progress tracking."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


class TestReadProgress:
    def test_reads_work_progress(self, tmp_path):
        from work_progress import read_progress
        (tmp_path / ".work-progress").write_text("step_a=done\nstep_b=pending\n")
        result = read_progress(tmp_path)
        assert result == {"step_a": "done", "step_b": "pending"}

    def test_falls_back_to_close_progress(self, tmp_path):
        from work_progress import read_progress
        (tmp_path / ".close-progress").write_text("review=done\n")
        result = read_progress(tmp_path)
        assert result == {"review": "done"}

    def test_prefers_work_progress_over_close(self, tmp_path):
        from work_progress import read_progress
        (tmp_path / ".work-progress").write_text("new=yes\n")
        (tmp_path / ".close-progress").write_text("old=yes\n")
        result = read_progress(tmp_path)
        assert result == {"new": "yes"}

    def test_empty_when_no_file(self, tmp_path):
        from work_progress import read_progress
        assert read_progress(tmp_path) == {}


class TestWriteProgress:
    def test_writes_to_work_progress(self, tmp_path):
        from work_progress import write_progress, read_progress
        write_progress(tmp_path, {"step_a": "done", "step_b": "pending"})
        assert (tmp_path / ".work-progress").exists()
        assert not (tmp_path / ".close-progress").exists()
        result = read_progress(tmp_path)
        assert result["step_a"] == "done"
        assert result["step_b"] == "pending"


class TestUpdateProgress:
    def test_creates_and_writes(self, tmp_path):
        from work_progress import update_progress, read_progress
        update_progress(tmp_path, "step_a", "done")
        assert (tmp_path / ".work-progress").exists()
        assert read_progress(tmp_path) == {"step_a": "done"}

    def test_preserves_existing_keys(self, tmp_path):
        from work_progress import update_progress, read_progress
        update_progress(tmp_path, "a", "1")
        update_progress(tmp_path, "b", "2")
        assert read_progress(tmp_path) == {"a": "1", "b": "2"}


class TestDeleteProgress:
    def test_removes_work_progress(self, tmp_path):
        from work_progress import update_progress, delete_progress
        update_progress(tmp_path, "a", "1")
        delete_progress(tmp_path)
        assert not (tmp_path / ".work-progress").exists()

    def test_removes_close_progress_too(self, tmp_path):
        from work_progress import delete_progress
        (tmp_path / ".close-progress").write_text("old=yes\n")
        delete_progress(tmp_path)
        assert not (tmp_path / ".close-progress").exists()

    def test_noop_when_no_files(self, tmp_path):
        from work_progress import delete_progress
        delete_progress(tmp_path)


class TestBackwardCompat:
    def test_compat_aliases_exist(self):
        from work_progress import (
            read_close_progress,
            write_close_progress,
            update_close_progress,
            delete_close_progress,
        )
        assert read_close_progress is not None
        assert write_close_progress is not None
        assert update_close_progress is not None
        assert delete_close_progress is not None

    def test_compat_read_reads_close_progress(self, tmp_path):
        from work_progress import read_close_progress
        (tmp_path / ".close-progress").write_text("old=yes\n")
        assert read_close_progress(tmp_path) == {"old": "yes"}

    def test_compat_update_writes_work_progress(self, tmp_path):
        from work_progress import update_close_progress
        update_close_progress(tmp_path, "key", "val")
        assert (tmp_path / ".work-progress").exists()


class TestIsStale:
    def test_empty_progress_not_stale(self):
        from work_progress import is_stale
        assert is_stale({}, "active") is False

    def test_progress_ahead_of_state_is_stale(self):
        from work_progress import is_stale
        progress = {"promote": "done"}
        assert is_stale(progress, "closing:review") is True

    def test_progress_at_state_not_stale(self):
        from work_progress import is_stale
        progress = {"code_review": "done"}
        assert is_stale(progress, "closing:review") is False
