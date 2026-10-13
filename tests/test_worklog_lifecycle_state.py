"""Tests for get_lifecycle_state() — Phase 1b prerequisite."""
import json
import sqlite3
import sys
from pathlib import Path

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

_lib = str(Path.home() / ".claude" / "lib")
if _lib not in sys.path:
    sys.path.insert(0, _lib)

import worklog


def _make_db():
    conn = worklog.connect(":memory:")
    return conn


def _ensure_work_item(conn, wid, branch=None, repo_path="/tmp/test"):
    if branch is None:
        branch = f"feature-{wid}"
    row = conn.execute("SELECT id FROM repos WHERE path=?", (repo_path,)).fetchone()
    if row:
        repo_id = row["id"]
    else:
        conn.execute(
            "INSERT INTO repos (path) VALUES (?)", (repo_path,))
        repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    existing = conn.execute(
        "SELECT id FROM work_items WHERE id=?", (wid,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO work_items (id, branch, repo_id, state, created_at) "
            "VALUES (?, ?, ?, 'active', datetime('now'))",
            (wid, branch, repo_id),
        )
    conn.commit()


def _insert_event(conn, work_item_id, event_type, to_state, from_state="idle"):
    _ensure_work_item(conn, work_item_id)
    metadata = json.dumps({"from_state": from_state, "to_state": to_state})
    conn.execute(
        "INSERT INTO events (timestamp, event_type, work_item_id, metadata) "
        "VALUES (datetime('now'), ?, ?, ?)",
        (event_type, work_item_id, metadata),
    )
    conn.commit()


def test_no_events_returns_none():
    conn = _make_db()
    result = worklog.get_lifecycle_state(conn, 999)
    assert result is None


def test_single_event_returns_state():
    conn = _make_db()
    _insert_event(conn, 1, "scaffolded", "scaffolded")
    result = worklog.get_lifecycle_state(conn, 1)
    assert result == "scaffolded"


def test_multiple_events_returns_most_recent():
    conn = _make_db()
    _insert_event(conn, 1, "scaffolded", "scaffolded")
    _insert_event(conn, 1, "activate", "active", from_state="scaffolded")
    _insert_event(conn, 1, "review_pass", "closing:review", from_state="active")
    result = worklog.get_lifecycle_state(conn, 1)
    assert result == "closing:review"


def test_different_work_items_isolated():
    conn = _make_db()
    _insert_event(conn, 1, "activate", "active")
    _insert_event(conn, 2, "review_pass", "closing:review")
    assert worklog.get_lifecycle_state(conn, 1) == "active"
    assert worklog.get_lifecycle_state(conn, 2) == "closing:review"


def test_event_without_to_state_skipped():
    conn = _make_db()
    _ensure_work_item(conn, 1)
    conn.execute(
        "INSERT INTO events (timestamp, event_type, work_item_id, metadata) "
        "VALUES (datetime('now'), 'info', 1, ?)",
        (json.dumps({"note": "no state"}),),
    )
    conn.commit()
    result = worklog.get_lifecycle_state(conn, 1)
    assert result is None
