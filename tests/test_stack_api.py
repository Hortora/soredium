"""Tests for project/stack.py library API — StackEntry, read/push/pop."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from stack import StackEntry, read_entries, push_entry, pop_entry


def test_read_empty_stack():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".pause-stack"
        assert read_entries(path) == []


def test_push_and_read():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".pause-stack"
        entry = StackEntry("issue-42", 42, "2026-08-11T00:00:00Z", True, False)
        depth = push_entry(path, entry)
        assert depth == 1
        entries = read_entries(path)
        assert len(entries) == 1
        assert entries[0].branch == "issue-42"
        assert entries[0].wip_project is True
        assert entries[0].wip_workspace is False


def test_push_appends():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".pause-stack"
        push_entry(path, StackEntry("issue-1", 1, "t1", True, True))
        push_entry(path, StackEntry("issue-2", 2, "t2", False, False))
        entries = read_entries(path)
        assert len(entries) == 2
        assert entries[0].branch == "issue-1"
        assert entries[1].branch == "issue-2"


def test_push_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".pause-stack"
        push_entry(path, StackEntry("issue-1", 1, "t1", True, True))
        push_entry(path, StackEntry("issue-1", 1, "t2", False, False))
        entries = read_entries(path)
        assert len(entries) == 1
        assert entries[0].paused == "t2"


def test_pop_entry():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".pause-stack"
        push_entry(path, StackEntry("issue-1", 1, "t1", True, True))
        push_entry(path, StackEntry("issue-2", 2, "t2", True, True))
        removed, depth = pop_entry(path, "issue-1")
        assert removed is True
        assert depth == 1
        entries = read_entries(path)
        assert entries[0].branch == "issue-2"


def test_pop_nonexistent():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".pause-stack"
        push_entry(path, StackEntry("issue-1", 1, "t1", True, True))
        removed, depth = pop_entry(path, "issue-99")
        assert removed is False
        assert depth == 1


def test_pop_from_empty():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".pause-stack"
        removed, depth = pop_entry(path, "issue-1")
        assert removed is False
        assert depth == 0


def test_existing_cli_cmd_depth_still_works():
    """Verify the existing CLI functions still work alongside new API."""
    from stack import cmd_depth, _read_entries
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".pause-stack"
        push_entry(path, StackEntry("issue-1", 1, "t1", True, True))
        raw = _read_entries(path)
        assert len(raw) == 1
        assert raw[0]["branch"] == "issue-1"
