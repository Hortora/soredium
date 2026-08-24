"""Tests for work-end/close_progress.py"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

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
