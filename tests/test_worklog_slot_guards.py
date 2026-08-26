"""Tests for fail_slot and find_reusable_slot worklog functions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import worklog as wl

import pytest


FAMILY = "/tmp/family"


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(wl, "DEFAULT_DB", str(db_path))
    conn = wl.connect()
    yield conn
    conn.close()


@pytest.fixture
def norm_family():
    return wl._norm(FAMILY)


class TestFailSlot:
    def test_transitions_pending_to_failed(self, db, norm_family):
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'pending', '2026-01-01')", (norm_family,))
        db.commit()
        wl.fail_slot(db, 1, FAMILY)
        row = db.execute(
            "SELECT state FROM slots WHERE slot_number=1 AND family_root=?",
            (norm_family,)).fetchone()
        assert row["state"] == "failed"

    def test_transitions_active_to_failed(self, db, norm_family):
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (2, ?, 'active', '2026-01-01')", (norm_family,))
        db.commit()
        wl.fail_slot(db, 2, FAMILY)
        row = db.execute(
            "SELECT state FROM slots WHERE slot_number=2 AND family_root=?",
            (norm_family,)).fetchone()
        assert row["state"] == "failed"

    def test_preserves_events(self, db, norm_family):
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (3, ?, 'active', '2026-01-01')", (norm_family,))
        db.commit()
        sid = db.execute("SELECT id FROM slots WHERE slot_number=3").fetchone()["id"]
        db.execute(
            "INSERT INTO events (event_type, timestamp, slot_id) "
            "VALUES ('slot-create', '2026-01-01', ?)", (sid,))
        db.commit()
        wl.fail_slot(db, 3, FAMILY)
        event = db.execute("SELECT * FROM events WHERE slot_id=?", (sid,)).fetchone()
        assert event is not None


class TestRecordSessionBoundary:
    def test_records_wrap_event(self, db, norm_family):
        wl.record_session_boundary(
            db, mode="wrap", branch="issue-42-test",
            issue_repo="org/repo", issue_number=42,
            steps={"forage": {"ran": True, "produced": 2}},
        )
        row = db.execute("SELECT * FROM session_boundaries").fetchone()
        assert row is not None
        assert row["mode"] == "wrap"
        assert row["branch"] == "issue-42-test"
        assert '"forage"' in row["steps_json"]

    def test_records_close_event(self, db, norm_family):
        wl.record_session_boundary(
            db, mode="close", branch="issue-99-fix",
            steps={"review": {"ran": True, "produced": 0}},
        )
        row = db.execute("SELECT * FROM session_boundaries WHERE mode='close'").fetchone()
        assert row is not None
        assert row["mode"] == "close"


class TestFindReusableSlot:
    def test_returns_highest_pending(self, db, norm_family):
        for n in (1, 3, 5):
            db.execute(
                "INSERT INTO slots (slot_number, family_root, state, created_at) "
                "VALUES (?, ?, 'pending', '2026-01-01')", (n, norm_family))
        db.commit()
        result = wl.find_reusable_slot(db, FAMILY)
        assert result is not None
        highest, others = result
        assert highest == 5
        assert sorted(others) == [1, 3]

    def test_includes_failed_slots(self, db, norm_family):
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (10, ?, 'failed', '2026-01-01')", (norm_family,))
        db.commit()
        result = wl.find_reusable_slot(db, FAMILY)
        assert result is not None
        assert result[0] == 10

    def test_returns_none_when_no_pending(self, db, norm_family):
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'active', '2026-01-01')", (norm_family,))
        db.commit()
        assert wl.find_reusable_slot(db, FAMILY) is None

    def test_ignores_active_slots(self, db, norm_family):
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'active', '2026-01-01')", (norm_family,))
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (2, ?, 'pending', '2026-01-01')", (norm_family,))
        db.commit()
        result = wl.find_reusable_slot(db, FAMILY)
        assert result is not None
        assert result[0] == 2
        assert result[1] == []
