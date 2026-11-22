"""Queue items carry scale and complexity metadata (#586)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))

from queue_io import Queue, QueueItem, QueueState, read_queue, write_queue  # noqa: E402


class TestQueueItemScaleComplexity:

    def test_parse_item_with_scale_and_complexity(self, tmp_path):
        (tmp_path / ".queue").write_text(
            "- [ ] o/r#1 — First task (S/Med)        ← active\n"
            "- [ ] o/r#2 — Second task (M/High)\n"
            "- [ ] o/r#3 — No metadata\n\n"
            "## State\nbranch: issue-1-x\nissue-repo: O/r\nstatus: active\n"
        )
        queue = read_queue(tmp_path)
        assert queue is not None
        assert queue.items[0].scale == "S"
        assert queue.items[0].complexity == "Med"
        assert queue.items[1].scale == "M"
        assert queue.items[1].complexity == "High"
        assert queue.items[2].scale == ""
        assert queue.items[2].complexity == ""

    def test_parse_preserves_title_without_scale(self, tmp_path):
        (tmp_path / ".queue").write_text(
            "- [ ] o/r#1 — First task (S/Med)        ← active\n\n"
            "## State\nbranch: x\nissue-repo: O/r\nstatus: active\n"
        )
        queue = read_queue(tmp_path)
        assert queue.items[0].title == "First task"

    def test_write_then_read_preserves_scale_complexity(self, tmp_path):
        original = Queue(
            items=[
                QueueItem(ref="o/r#1", title="First", completed=False, active=True,
                          scale="S", complexity="Med"),
                QueueItem(ref="o/r#2", title="Second", completed=False, active=False),
            ],
            state=QueueState(branch="issue-1-x", issue_repo="O/r", status="active",
                             covers="o/r#1"))
        write_queue(tmp_path, original)
        reloaded = read_queue(tmp_path)
        assert reloaded.items[0].scale == "S"
        assert reloaded.items[0].complexity == "Med"
        assert reloaded.items[0].title == "First"
        assert reloaded.items[1].scale == ""
        assert reloaded.items[1].complexity == ""

    def test_scale_and_from_main_coexist(self, tmp_path):
        original = Queue(
            items=[
                QueueItem(ref="o/r#1", title="Task", completed=False, active=True,
                          scale="L", complexity="High", from_main=True),
            ],
            state=QueueState(branch="x", issue_repo="O/r", status="active"))
        write_queue(tmp_path, original)
        reloaded = read_queue(tmp_path)
        assert reloaded.items[0].scale == "L"
        assert reloaded.items[0].complexity == "High"
        assert reloaded.items[0].from_main is True
        assert reloaded.items[0].title == "Task"


class TestSetScale:

    def test_set_scale_updates_item(self, tmp_path):
        write_queue(tmp_path, Queue(
            items=[
                QueueItem(ref="o/r#1", title="First", completed=False, active=True),
                QueueItem(ref="o/r#2", title="Second", completed=False, active=False),
            ],
            state=QueueState(branch="x", issue_repo="O/r", status="active")))
        result = subprocess.run(
            ["python3", str(ROOT / "work-slot" / "plan_manager.py"),
             "set-scale", str(tmp_path / ".queue"),
             "ref=o/r#1", "scale=S", "complexity=Med"],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stderr + result.stdout
        reloaded = read_queue(tmp_path)
        assert reloaded.items[0].scale == "S"
        assert reloaded.items[0].complexity == "Med"
        assert reloaded.items[0].title == "First"

    def test_set_scale_on_missing_ref_fails(self, tmp_path):
        write_queue(tmp_path, Queue(
            items=[QueueItem(ref="o/r#1", title="First", completed=False, active=True)],
            state=QueueState(branch="x", issue_repo="O/r", status="active")))
        result = subprocess.run(
            ["python3", str(ROOT / "work-slot" / "plan_manager.py"),
             "set-scale", str(tmp_path / ".queue"),
             "ref=o/r#99", "scale=S", "complexity=Med"],
            capture_output=True, text=True)
        assert result.returncode == 1
