"""Tests for project.queue_io — .queue reader/writer with .plan migration."""
from __future__ import annotations

import pytest
from pathlib import Path

from project.queue_io import (
    read_queue, write_queue, Queue, QueueItem, QueueState,
    migrate_plan_to_queue, parse_covers, parse_covers_qualified, CoverRef,
)


# --- read / write basics ---

def test_read_queue_basic(tmp_path):
    (tmp_path / ".queue").write_text(
        "- [x] Hortora/soredium#381 — Implement batch processing\n"
        "- [ ] Hortora/soredium#382 — Add retry logic        ← active\n"
        "- [ ] Hortora/soredium#383 — Dashboard metrics\n"
        "\n"
        "## State\n"
        "branch: issue-382-retry-logic\n"
        "issue-repo: Hortora/soredium\n"
        "status: active\n"
    )
    q = read_queue(tmp_path)
    assert q is not None
    assert len(q.items) == 3
    assert q.items[0].completed is True
    assert q.items[0].ref == "Hortora/soredium#381"
    assert q.items[1].active is True
    assert q.items[1].ref == "Hortora/soredium#382"
    assert q.items[2].ref == "Hortora/soredium#383"
    assert q.state.branch == "issue-382-retry-logic"
    assert q.state.issue_repo == "Hortora/soredium"
    assert q.state.status == "active"


def test_read_queue_no_file(tmp_path):
    q = read_queue(tmp_path)
    assert q is None


def test_active_item(tmp_path):
    (tmp_path / ".queue").write_text(
        "- [x] Hortora/soredium#381 — Done\n"
        "- [ ] Hortora/soredium#382 — Active        ← active\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
    )
    q = read_queue(tmp_path)
    assert q.active_item().ref == "Hortora/soredium#382"


def test_complete_active_and_activate_next(tmp_path):
    (tmp_path / ".queue").write_text(
        "- [ ] R#1 — First        ← active\n"
        "- [ ] R#2 — Second\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
    )
    q = read_queue(tmp_path)
    q.complete_active()
    assert q.items[0].completed is True
    assert q.items[0].active is False
    assert q.has_next() is True
    q.activate_next()
    assert q.items[1].active is True
    assert q.active_item().ref == "R#2"


def test_complete_last_item_drains(tmp_path):
    (tmp_path / ".queue").write_text(
        "- [ ] R#1 — Only        ← active\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
    )
    q = read_queue(tmp_path)
    q.complete_active()
    assert q.has_next() is False
    q.set_status("drained")
    assert q.state.status == "drained"


def test_invalid_status_raises(tmp_path):
    (tmp_path / ".queue").write_text(
        "- [ ] R#1 — Task        ← active\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
    )
    q = read_queue(tmp_path)
    with pytest.raises(ValueError, match="invalid status"):
        q.set_status("closing:promoted")


def test_write_queue_roundtrip(tmp_path):
    (tmp_path / ".queue").write_text(
        "- [x] R#1 — Done\n"
        "- [ ] R#2 — Active        ← active\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
    )
    q = read_queue(tmp_path)
    write_queue(tmp_path, q)
    q2 = read_queue(tmp_path)
    assert len(q2.items) == len(q.items)
    assert q2.state.branch == q.state.branch
    assert q2.active_item().ref == q.active_item().ref


# --- .plan migration ---

def test_migrate_plan_to_queue(tmp_path):
    (tmp_path / ".plan").write_text(
        "- [ ] R#1 — Task        ← active\n"
        "\n## State\n"
        "branch: issue-1-task\n"
        "state: active\n"
        "issue-repo: R\n"
        "covers: R#1\n"
    )
    q = read_queue(tmp_path)
    assert q is not None
    assert q.state.status == "active"
    assert q.state.branch == "issue-1-task"
    assert (tmp_path / ".queue").exists()
    assert (tmp_path / ".plan.bak").exists()


def test_migrate_closing_state(tmp_path):
    (tmp_path / ".plan").write_text(
        "- [ ] R#1 — Task        ← active\n"
        "\n## State\n"
        "branch: b\n"
        "state: closing:promoted\n"
        "issue-repo: R\n"
    )
    q = read_queue(tmp_path)
    assert q.state.status == "active"


def test_no_migration_if_queue_exists(tmp_path):
    (tmp_path / ".queue").write_text(
        "- [ ] R#1 — Queue        ← active\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
    )
    (tmp_path / ".plan").write_text(
        "- [ ] R#2 — Plan        ← active\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
    )
    q = read_queue(tmp_path)
    assert q.active_item().ref == "R#1"


def test_preserves_deferred_section(tmp_path):
    (tmp_path / ".queue").write_text(
        "- [ ] R#1 — Task        ← active\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
        "\n## Deferred\n"
        "- Deferred item (M / Med)\n"
    )
    q = read_queue(tmp_path)
    assert len(q.deferred_lines) > 0
    write_queue(tmp_path, q)
    q2 = read_queue(tmp_path)
    assert len(q2.deferred_lines) == len(q.deferred_lines)


# --- covers parsing (migrated from plan_io) ---

def test_parse_covers_bare_numbers():
    assert parse_covers("1, 2, 3") == [1, 2, 3]
    assert parse_covers("42") == [42]


def test_parse_covers_qualified():
    refs = parse_covers_qualified("Hortora/soredium#499, Hortora/soredium#498")
    assert len(refs) == 2
    assert refs[0].repo == "Hortora/soredium"
    assert refs[0].number == 499


def test_parse_covers_qualified_mixed():
    refs = parse_covers_qualified("Hortora/soredium#499, 42")
    assert len(refs) == 2
    assert refs[0].repo == "Hortora/soredium"
    assert refs[1].number == 42
    assert refs[1].repo == ""


# --- edge cases ---

def test_queue_with_nested_tasks(tmp_path):
    """Queue items may have indented sub-tasks (batch structure)."""
    (tmp_path / ".queue").write_text(
        "- [ ] R#1 — First        ← active\n"
        "  - [ ] Sub-task A\n"
        "  - [x] Sub-task B\n"
        "- [ ] R#2 — Second\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
    )
    q = read_queue(tmp_path)
    assert len(q.items) == 2
    assert q.items[0].ref == "R#1"


def test_queue_with_covers_field(tmp_path):
    """covers: field in State section is preserved."""
    (tmp_path / ".queue").write_text(
        "- [ ] R#1 — Task        ← active\n"
        "\n## State\nbranch: b\nissue-repo: R\nstatus: active\n"
        "covers: R#1\n"
    )
    q = read_queue(tmp_path)
    assert q.state.covers == "R#1"
    write_queue(tmp_path, q)
    q2 = read_queue(tmp_path)
    assert q2.state.covers == "R#1"
