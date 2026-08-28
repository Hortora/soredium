"""Tests for work-slot/slot_observability.py"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_observability


class TestRecordWorklog:
    def test_returns_false_when_wl_unavailable(self):
        with patch.object(slot_observability, "_wl", None):
            assert slot_observability.record_worklog("record_slot_merge") is False

    def test_calls_named_function(self):
        mock_wl = MagicMock()
        with patch.object(slot_observability, "_wl", mock_wl):
            result = slot_observability.record_worklog(
                "record_slot_merge", "conn", 1, "/path"
            )
        assert result is True
        mock_wl.record_slot_merge.assert_called_once_with("conn", 1, "/path")

    def test_returns_false_on_missing_function(self):
        mock_wl = MagicMock(spec=[])
        with patch.object(slot_observability, "_wl", mock_wl):
            assert slot_observability.record_worklog("nonexistent_func") is False

    def test_returns_false_on_exception(self):
        mock_wl = MagicMock()
        mock_wl.record_slot_merge.side_effect = Exception("db error")
        with patch.object(slot_observability, "_wl", mock_wl):
            assert slot_observability.record_worklog("record_slot_merge") is False


class TestGetWorklog:
    def test_returns_module_when_available(self):
        mock_wl = MagicMock()
        with patch.object(slot_observability, "_wl", mock_wl):
            assert slot_observability.get_worklog() is mock_wl

    def test_returns_none_when_unavailable(self):
        with patch.object(slot_observability, "_wl", None):
            assert slot_observability.get_worklog() is None
