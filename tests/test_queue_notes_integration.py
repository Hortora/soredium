"""Tests that queue_io and plan_manager use the notes store when available."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from notes_store import NotesStore
from queue_io import read_queue, write_queue, queue_dir, Queue, QueueItem, QueueState


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )


@pytest.fixture
def workspace_with_notes(tmp_path):
    """A workspace with an initialized notes store."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(ws, "init", "-b", "main")
    _git(ws, "config", "user.email", "test@test.com")
    _git(ws, "config", "user.name", "Test")
    _git(ws, "commit", "--allow-empty", "-m", "init")
    store = NotesStore(ws)
    store.ensure()
    return ws


@pytest.fixture
def workspace_without_notes(tmp_path):
    """A workspace without a notes store — legacy behaviour."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(ws, "init", "-b", "main")
    _git(ws, "config", "user.email", "test@test.com")
    _git(ws, "config", "user.name", "Test")
    _git(ws, "commit", "--allow-empty", "-m", "init")
    return ws


class TestQueueDirResolution:
    def test_queue_dir_returns_notes_when_available(self, workspace_with_notes):
        assert queue_dir(workspace_with_notes) == workspace_with_notes / ".notes"

    def test_queue_dir_returns_workspace_when_no_notes(self, workspace_without_notes):
        assert queue_dir(workspace_without_notes) == workspace_without_notes


class TestReadQueueWithNotes:
    def test_reads_from_notes_when_available(self, workspace_with_notes):
        store = NotesStore(workspace_with_notes)
        store.write(".queue", (
            "- [ ] #1 — First item        ← active\n"
            "\n"
            "## State\n"
            "branch: issue-1\n"
            "issue-repo: Hortora/soredium\n"
            "status: active\n"
        ), "seed queue")

        q = read_queue(workspace_with_notes)
        assert q is not None
        assert len(q.items) == 1
        assert q.items[0].ref == "#1"
        assert q.state.status == "active"

    def test_ignores_workspace_queue_when_notes_has_one(self, workspace_with_notes):
        store = NotesStore(workspace_with_notes)
        store.write(".queue", (
            "- [ ] #1 — From notes        ← active\n"
            "\n## State\nstatus: active\nbranch: b\nissue-repo: R\n"
        ), "notes queue")
        (workspace_with_notes / ".queue").write_text(
            "- [ ] #2 — From workspace        ← active\n"
            "\n## State\nstatus: active\nbranch: b\nissue-repo: R\n"
        )

        q = read_queue(workspace_with_notes)
        assert q.items[0].ref == "#1"

    def test_falls_back_to_workspace_when_no_notes_store(self, workspace_without_notes):
        (workspace_without_notes / ".queue").write_text(
            "- [ ] #1 — From workspace        ← active\n"
            "\n## State\nstatus: active\nbranch: b\nissue-repo: R\n"
        )
        q = read_queue(workspace_without_notes)
        assert q is not None
        assert q.items[0].ref == "#1"

    def test_reading_through_notes_never_writes(self, workspace_with_notes):
        """read_queue through notes store changes no file."""
        store = NotesStore(workspace_with_notes)
        store.write(".queue", (
            "- [ ] #1 — First        ← active\n"
            "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
        ), "seed queue")

        notes_sha = _git(workspace_with_notes / ".notes", "rev-parse", "HEAD").stdout.strip()
        ws_status = _git(workspace_with_notes, "status", "--porcelain").stdout

        read_queue(workspace_with_notes)
        read_queue(workspace_with_notes)

        assert _git(workspace_with_notes / ".notes", "rev-parse", "HEAD").stdout.strip() == notes_sha
        assert _git(workspace_with_notes, "status", "--porcelain").stdout == ws_status


class TestWriteQueueWithNotes:
    def test_writes_to_notes_and_commits(self, workspace_with_notes):
        q = Queue(
            items=[QueueItem(ref="#1", title="Test", completed=False, active=True)],
            state=QueueState(branch="issue-1", issue_repo="Hortora/soredium", status="active"),
        )
        write_queue(workspace_with_notes, q)

        notes_queue = workspace_with_notes / ".notes" / ".queue"
        assert notes_queue.is_file()
        content = notes_queue.read_text()
        assert "#1 — Test" in content

        log = _git(workspace_with_notes / ".notes", "log", "--oneline").stdout
        assert "update queue" in log

    def test_does_not_write_to_workspace_when_notes_available(self, workspace_with_notes):
        q = Queue(
            items=[QueueItem(ref="#1", title="Test", completed=False, active=True)],
            state=QueueState(branch="b", issue_repo="R", status="active"),
        )
        write_queue(workspace_with_notes, q)

        assert not (workspace_with_notes / ".queue").exists()

    def test_writes_to_workspace_when_no_notes(self, workspace_without_notes):
        q = Queue(
            items=[QueueItem(ref="#1", title="Test", completed=False, active=True)],
            state=QueueState(branch="b", issue_repo="R", status="active"),
        )
        write_queue(workspace_without_notes, q)

        assert (workspace_without_notes / ".queue").is_file()
        content = (workspace_without_notes / ".queue").read_text()
        assert "#1 — Test" in content

    def test_roundtrip_through_notes(self, workspace_with_notes):
        q = Queue(
            items=[
                QueueItem(ref="#1", title="Done", completed=True, active=False),
                QueueItem(ref="#2", title="Active", completed=False, active=True),
                QueueItem(ref="#3", title="Next", completed=False, active=False),
            ],
            state=QueueState(branch="issue-2", issue_repo="Hortora/soredium", status="active"),
        )
        write_queue(workspace_with_notes, q)
        q2 = read_queue(workspace_with_notes)

        assert q2 is not None
        assert len(q2.items) == 3
        assert q2.items[0].completed
        assert q2.items[1].active
        assert q2.state.branch == "issue-2"


class TestPlanManagerWithNotes:
    def test_rewrite_plan_commits_in_notes(self, workspace_with_notes):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))
        from plan_manager import parse_plan, rewrite_plan

        store = NotesStore(workspace_with_notes)
        plan_content = (
            "# Work Plan — test\n\n"
            "- [ ] Hortora/soredium#1 — First        ← active\n\n"
            "## State\n"
            "branch: issue-1\n"
            "issue-repo: Hortora/soredium\n"
            "status: active\n"
            "started: 2026-11-19\n"
        )
        store.write(".queue", plan_content, "seed")

        plan_path = workspace_with_notes / ".notes" / ".queue"
        tree = parse_plan(plan_path)
        rewrite_plan(plan_path, tree)

        log = _git(workspace_with_notes / ".notes", "log", "--oneline").stdout
        assert "update queue" in log
