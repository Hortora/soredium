"""Tests for scripts/worklog.py"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import worklog


class TestConnect:
    def test_creates_db_and_tables(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn = worklog.connect(str(db))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        assert "repos" in tables
        assert "work_items" in tables
        assert "work_item_issues" in tables
        assert "slots" in tables
        assert "events" in tables
        conn.close()

    def test_wal_mode_enabled(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn = worklog.connect(str(db))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_creates_parent_directories(self, tmp_path):
        db = tmp_path / "sub" / "dir" / "worklog.db"
        conn = worklog.connect(str(db))
        assert db.exists()
        conn.close()

    def test_schema_version_set(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn = worklog.connect(str(db))
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 2
        conn.close()

    def test_idempotent_connect(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn1 = worklog.connect(str(db))
        conn1.close()
        conn2 = worklog.connect(str(db))
        ver = conn2.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 2
        conn2.close()


class TestEnsureRepo:
    def test_inserts_new_repo(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        rid = worklog.ensure_repo(conn, "/path/to/engine",
                                  workspace="/path/to/ws",
                                  github_repo="casehubio/engine")
        assert rid is not None
        row = conn.execute("SELECT * FROM repos WHERE id=?", (rid,)).fetchone()
        assert row["path"] == "/path/to/engine"
        assert row["github_repo"] == "casehubio/engine"
        conn.close()

    def test_returns_existing_repo_id(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        r1 = worklog.ensure_repo(conn, "/path/to/engine")
        r2 = worklog.ensure_repo(conn, "/path/to/engine")
        assert r1 == r2
        conn.close()

    def test_updates_fields_on_existing(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/path/to/engine")
        worklog.ensure_repo(conn, "/path/to/engine",
                            github_repo="casehubio/engine")
        row = conn.execute(
            "SELECT github_repo FROM repos WHERE path=?",
            ("/path/to/engine",)
        ).fetchone()
        assert row["github_repo"] == "casehubio/engine"
        conn.close()


class TestRecordWorkStart:
    def test_creates_work_item_and_event(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/repo/engine")
        wid = worklog.record_work_start(
            conn, "issue-42-spi", "/repo/engine",
            issue_number=42, issue_repo="casehubio/engine",
            covers="42,43",
        )
        assert wid is not None
        wi = conn.execute("SELECT * FROM work_items WHERE id=?", (wid,)).fetchone()
        assert wi["branch"] == "issue-42-spi"
        assert wi["state"] == "active"
        assert wi["location"] == "primary"
        issues = conn.execute(
            "SELECT * FROM work_item_issues WHERE work_item_id=? ORDER BY issue_number",
            (wid,)
        ).fetchall()
        assert len(issues) == 2
        assert issues[0]["issue_number"] == 42
        assert issues[0]["is_primary"] == 1
        assert issues[1]["issue_number"] == 43
        assert issues[1]["is_primary"] == 0
        evts = conn.execute(
            "SELECT * FROM events WHERE work_item_id=?", (wid,)
        ).fetchall()
        assert len(evts) == 1
        assert evts[0]["event_type"] == "work-start"
        conn.close()

    def test_single_issue(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/repo/engine")
        wid = worklog.record_work_start(
            conn, "issue-42-spi", "/repo/engine",
            issue_number=42, issue_repo="casehubio/engine",
        )
        issues = conn.execute(
            "SELECT * FROM work_item_issues WHERE work_item_id=?", (wid,)
        ).fetchall()
        assert len(issues) == 1
        assert issues[0]["is_primary"] == 1
        conn.close()

    def test_slot_location(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/repo/engine")
        sid = worklog.record_slot_create(conn, 3, "/family",
                                         repos=["/repo/engine"],
                                         branch="issue-42-spi",
                                         issue_number=42, issue_repo="org/repo",
                                         covers="42")
        wid = worklog.record_work_start(
            conn, "issue-99-other", "/repo/engine",
            issue_number=99, issue_repo="org/repo",
            location="slot", slot_id=sid,
        )
        wi = conn.execute("SELECT * FROM work_items WHERE id=?", (wid,)).fetchone()
        assert wi["location"] == "slot"
        assert wi["slot_id"] == sid
        conn.close()


class TestWorkItemLifecycle:
    def _start(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/repo/engine")
        wid = worklog.record_work_start(
            conn, "issue-42-spi", "/repo/engine",
            issue_number=42, issue_repo="org/repo",
        )
        return conn, wid

    def test_pause(self, tmp_path):
        conn, wid = self._start(tmp_path)
        worklog.record_work_pause(conn, "issue-42-spi", "/repo/engine")
        wi = conn.execute("SELECT state FROM work_items WHERE id=?", (wid,)).fetchone()
        assert wi["state"] == "paused"
        evts = conn.execute(
            "SELECT event_type FROM events WHERE work_item_id=? ORDER BY id",
            (wid,)
        ).fetchall()
        assert [e["event_type"] for e in evts] == ["work-start", "work-pause"]
        conn.close()

    def test_resume(self, tmp_path):
        conn, wid = self._start(tmp_path)
        worklog.record_work_pause(conn, "issue-42-spi", "/repo/engine")
        worklog.record_work_resume(conn, "issue-42-spi", "/repo/engine")
        wi = conn.execute("SELECT state FROM work_items WHERE id=?", (wid,)).fetchone()
        assert wi["state"] == "active"
        conn.close()

    def test_end(self, tmp_path):
        conn, wid = self._start(tmp_path)
        worklog.record_work_end(conn, "issue-42-spi", "/repo/engine",
                                landed_sha="abc123")
        wi = conn.execute("SELECT * FROM work_items WHERE id=?", (wid,)).fetchone()
        assert wi["state"] == "ended"
        assert wi["ended_at"] is not None
        evt = conn.execute(
            "SELECT metadata FROM events WHERE work_item_id=? AND event_type='work-end'",
            (wid,)
        ).fetchone()
        meta = json.loads(evt["metadata"])
        assert meta["landed_sha"] == "abc123"
        conn.close()

    def test_end_without_start_is_nonfatal(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        result = worklog.record_work_end(conn, "nonexistent", "/repo/x")
        assert result is None
        conn.close()


class TestSlotLifecycle:
    def _create(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/family/engine")
        worklog.ensure_repo(conn, "/family/iot")
        sid = worklog.record_slot_create(
            conn, 3, "/family",
            repos=["/family/engine", "/family/iot"],
            branch="issue-42-spi",
            issue_number=42, issue_repo="org/repo",
            covers="42,43",
        )
        return conn, sid

    def test_create(self, tmp_path):
        conn, sid = self._create(tmp_path)
        slot = conn.execute("SELECT * FROM slots WHERE id=?", (sid,)).fetchone()
        assert slot["slot_number"] == 3
        assert slot["family_root"] == "/family"
        assert slot["state"] == "active"
        wis = conn.execute(
            "SELECT * FROM work_items WHERE slot_id=?", (sid,)
        ).fetchall()
        assert len(wis) == 2
        assert all(w["location"] == "slot" for w in wis)
        evts = conn.execute(
            "SELECT * FROM events WHERE slot_id=?", (sid,)
        ).fetchall()
        assert any(e["event_type"] == "slot-create" for e in evts)
        conn.close()

    def test_phase_a(self, tmp_path):
        conn, sid = self._create(tmp_path)
        worklog.record_slot_phase_a(conn, 3, "/family")
        slot = conn.execute("SELECT state FROM slots WHERE id=?", (sid,)).fetchone()
        assert slot["state"] == "ready"
        conn.close()

    def test_merge(self, tmp_path):
        conn, sid = self._create(tmp_path)
        worklog.record_slot_merge(conn, 3, "/family",
                                  landed_shas={"engine": "abc", "iot": "def"})
        slot = conn.execute("SELECT state FROM slots WHERE id=?", (sid,)).fetchone()
        assert slot["state"] == "landed"
        wis = conn.execute(
            "SELECT state FROM work_items WHERE slot_id=?", (sid,)
        ).fetchall()
        assert all(w["state"] == "ended" for w in wis)
        conn.close()

    def test_archive(self, tmp_path):
        conn, sid = self._create(tmp_path)
        worklog.record_slot_merge(conn, 3, "/family",
                                  landed_shas={"engine": "abc"})
        worklog.record_slot_archive(conn, 3, "/family")
        slot = conn.execute("SELECT * FROM slots WHERE id=?", (sid,)).fetchone()
        assert slot["state"] == "archived"
        assert slot["archived_at"] is not None
        conn.close()


class TestQueries:
    def _setup(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/repo/engine", github_repo="org/engine")
        worklog.ensure_repo(conn, "/repo/iot", github_repo="org/iot")
        worklog.record_work_start(conn, "issue-42-spi", "/repo/engine",
                                  issue_number=42, issue_repo="org/engine")
        worklog.record_work_start(conn, "issue-55-fix", "/repo/iot",
                                  issue_number=55, issue_repo="org/iot")
        worklog.record_work_pause(conn, "issue-55-fix", "/repo/iot")
        return conn

    def test_active_work(self, tmp_path):
        conn = self._setup(tmp_path)
        result = worklog.active_work(conn)
        assert len(result) == 2
        branches = {r["branch"] for r in result}
        assert "issue-42-spi" in branches
        assert "issue-55-fix" in branches
        conn.close()

    def test_active_work_excludes_ended(self, tmp_path):
        conn = self._setup(tmp_path)
        worklog.record_work_end(conn, "issue-42-spi", "/repo/engine")
        result = worklog.active_work(conn)
        assert len(result) == 1
        assert result[0]["branch"] == "issue-55-fix"
        conn.close()

    def test_slot_status(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/family/engine")
        worklog.record_slot_create(conn, 1, "/family",
                                   repos=["/family/engine"],
                                   branch="issue-10-x",
                                   issue_number=10, issue_repo="org/r")
        result = worklog.slot_status(conn)
        assert len(result) == 1
        assert result[0]["slot_number"] == 1
        assert result[0]["state"] == "active"
        conn.close()

    def test_slot_status_filter_family(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/familyA/engine")
        worklog.ensure_repo(conn, "/familyB/engine")
        worklog.record_slot_create(conn, 1, "/familyA",
                                   repos=["/familyA/engine"],
                                   branch="b1", issue_number=1,
                                   issue_repo="org/r")
        worklog.record_slot_create(conn, 1, "/familyB",
                                   repos=["/familyB/engine"],
                                   branch="b2", issue_number=2,
                                   issue_repo="org/r")
        result = worklog.slot_status(conn, family_root="/familyA")
        assert len(result) == 1
        conn.close()

    def test_event_log(self, tmp_path):
        conn = self._setup(tmp_path)
        result = worklog.event_log(conn)
        assert len(result) >= 3
        conn.close()

    def test_event_log_filter_type(self, tmp_path):
        conn = self._setup(tmp_path)
        result = worklog.event_log(conn, event_type="work-pause")
        assert len(result) == 1
        conn.close()

    def test_work_item_timeline(self, tmp_path):
        conn = self._setup(tmp_path)
        worklog.record_work_resume(conn, "issue-55-fix", "/repo/iot")
        worklog.record_work_end(conn, "issue-55-fix", "/repo/iot")
        result = worklog.work_item_timeline(conn, "issue-55-fix", "/repo/iot")
        types = [r["event_type"] for r in result]
        assert types == ["work-start", "work-pause", "work-resume", "work-end"]
        conn.close()


class TestFullWorkItemLifecycle:
    def test_start_pause_resume_end_timeline(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/repo/engine", github_repo="org/engine")

        wid = worklog.record_work_start(
            conn, "issue-42-spi", "/repo/engine",
            issue_number=42, issue_repo="org/engine", covers="42,43",
        )
        wi = conn.execute("SELECT * FROM work_items WHERE id=?", (wid,)).fetchone()
        assert wi["state"] == "active"
        assert wi["location"] == "primary"
        assert worklog.active_work(conn)[0]["branch"] == "issue-42-spi"

        worklog.record_work_pause(conn, "issue-42-spi", "/repo/engine")
        wi = conn.execute("SELECT state FROM work_items WHERE id=?", (wid,)).fetchone()
        assert wi["state"] == "paused"
        assert len(worklog.active_work(conn)) == 1

        worklog.record_work_resume(conn, "issue-42-spi", "/repo/engine")
        wi = conn.execute("SELECT state FROM work_items WHERE id=?", (wid,)).fetchone()
        assert wi["state"] == "active"

        worklog.record_work_end(conn, "issue-42-spi", "/repo/engine", landed_sha="abc123")
        wi = conn.execute("SELECT * FROM work_items WHERE id=?", (wid,)).fetchone()
        assert wi["state"] == "ended"
        assert wi["ended_at"] is not None
        assert len(worklog.active_work(conn)) == 0

        timeline = worklog.work_item_timeline(conn, "issue-42-spi", "/repo/engine")
        types = [e["event_type"] for e in timeline]
        assert types == ["work-start", "work-pause", "work-resume", "work-end"]

        issues = conn.execute(
            "SELECT * FROM work_item_issues WHERE work_item_id=? ORDER BY issue_number",
            (wid,)
        ).fetchall()
        assert len(issues) == 2
        assert issues[0]["issue_number"] == 42
        assert issues[0]["is_primary"] == 1
        assert issues[1]["issue_number"] == 43
        assert issues[1]["is_primary"] == 0
        conn.close()


class TestFullSlotLifecycle:
    def test_create_phase_a_merge_archive_timeline(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/family/engine")
        worklog.ensure_repo(conn, "/family/iot")

        sid = worklog.record_slot_create(
            conn, 5, "/family",
            repos=["/family/engine", "/family/iot"],
            branch="issue-42-spi",
            issue_number=42, issue_repo="org/repo", covers="42,43",
        )
        slot = conn.execute("SELECT * FROM slots WHERE id=?", (sid,)).fetchone()
        assert slot["state"] == "active"
        wis = conn.execute("SELECT * FROM work_items WHERE slot_id=?", (sid,)).fetchall()
        assert len(wis) == 2
        assert all(w["state"] == "active" for w in wis)
        assert all(w["location"] == "slot" for w in wis)
        assert len(worklog.active_work(conn)) == 2
        assert worklog.slot_status(conn)[0]["state"] == "active"

        worklog.record_slot_phase_a(conn, 5, "/family")
        slot = conn.execute("SELECT state FROM slots WHERE id=?", (sid,)).fetchone()
        assert slot["state"] == "ready"
        assert worklog.slot_status(conn)[0]["state"] == "ready"

        worklog.record_slot_merge(conn, 5, "/family",
                                  landed_shas={"engine": "sha1", "iot": "sha2"})
        slot = conn.execute("SELECT state FROM slots WHERE id=?", (sid,)).fetchone()
        assert slot["state"] == "landed"
        wis = conn.execute("SELECT state FROM work_items WHERE slot_id=?", (sid,)).fetchall()
        assert all(w["state"] == "ended" for w in wis)
        assert len(worklog.active_work(conn)) == 0

        worklog.record_slot_archive(conn, 5, "/family")
        slot = conn.execute("SELECT * FROM slots WHERE id=?", (sid,)).fetchone()
        assert slot["state"] == "archived"
        assert slot["archived_at"] is not None

        events = conn.execute(
            "SELECT event_type FROM events WHERE slot_id=? ORDER BY id", (sid,)
        ).fetchall()
        types = [e["event_type"] for e in events]
        assert types == ["slot-create", "slot-phase-a", "slot-merge", "slot-archive"]

        merge_evt = conn.execute(
            "SELECT metadata FROM events WHERE slot_id=? AND event_type='slot-merge'",
            (sid,)
        ).fetchone()
        meta = json.loads(merge_evt["metadata"])
        assert meta["landed_shas"]["engine"] == "sha1"
        assert meta["landed_shas"]["iot"] == "sha2"
        conn.close()


class TestFailureIsolation:
    def test_safe_decorator_catches_exceptions(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        conn.close()
        result = worklog.record_work_start(
            conn, "branch", "/repo", issue_number=1, issue_repo="org/r"
        )
        assert result is None

    def test_ensure_repo_on_closed_conn(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        conn.close()
        result = worklog.ensure_repo(conn, "/repo")
        assert result is None

    def test_record_pause_unknown_branch(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        result = worklog.record_work_pause(conn, "nonexistent", "/repo")
        assert result is None
        conn.close()

    def test_concurrent_connections(self, tmp_path):
        db = str(tmp_path / "wl.db")
        conn1 = worklog.connect(db)
        conn2 = worklog.connect(db)
        worklog.ensure_repo(conn1, "/repo/a")
        worklog.ensure_repo(conn2, "/repo/b")
        repos = conn1.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
        assert repos == 2
        conn1.close()
        conn2.close()


class TestFindWorkItem:
    def test_find_by_branch_and_repo(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/tmp/test-repo")
        wid = worklog.record_work_start(
            conn, "issue-1-foo", "/tmp/test-repo",
            issue_number=1, issue_repo="org/repo",
        )
        found = worklog.find_work_item(conn, "issue-1-foo", "/tmp/test-repo")
        assert found == wid
        conn.close()

    def test_find_returns_none_when_missing(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        found = worklog.find_work_item(conn, "nonexistent", "/tmp/nope")
        assert found is None
        conn.close()

    def test_find_fallback_by_branch_only(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/tmp/test-repo")
        wid = worklog.record_work_start(
            conn, "issue-2-bar", "/tmp/test-repo",
            issue_number=2, issue_repo="org/repo",
        )
        found = worklog.find_work_item(conn, "issue-2-bar", "/tmp/other-path")
        assert found == wid
        conn.close()


class TestUpdateWorkItemState:
    def test_update_to_paused(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/tmp/test-repo")
        wid = worklog.record_work_start(
            conn, "issue-1-foo", "/tmp/test-repo",
            issue_number=1, issue_repo="org/repo",
        )
        worklog.update_work_item_state(conn, wid, "paused")
        row = conn.execute(
            "SELECT state FROM work_items WHERE id=?", (wid,)
        ).fetchone()
        assert row["state"] == "paused"
        conn.close()

    def test_update_to_ended_sets_ended_at(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/tmp/test-repo")
        wid = worklog.record_work_start(
            conn, "issue-1-foo", "/tmp/test-repo",
            issue_number=1, issue_repo="org/repo",
        )
        worklog.update_work_item_state(conn, wid, "ended")
        row = conn.execute(
            "SELECT state, ended_at FROM work_items WHERE id=?", (wid,)
        ).fetchone()
        assert row["state"] == "ended"
        assert row["ended_at"] is not None
        conn.close()

    def test_update_to_active_from_paused(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/tmp/test-repo")
        wid = worklog.record_work_start(
            conn, "issue-1-foo", "/tmp/test-repo",
            issue_number=1, issue_repo="org/repo",
        )
        worklog.update_work_item_state(conn, wid, "paused")
        worklog.update_work_item_state(conn, wid, "active")
        row = conn.execute(
            "SELECT state FROM work_items WHERE id=?", (wid,)
        ).fetchone()
        assert row["state"] == "active"
        conn.close()


class TestLogTransition:
    def test_log_transition_writes_event(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/tmp/test-repo")
        wid = worklog.record_work_start(
            conn, "issue-1-foo", "/tmp/test-repo",
            issue_number=1, issue_repo="org/repo",
        )
        worklog.log_transition(
            conn, "work_pause", work_item_id=wid,
            repo_path="/tmp/test-repo",
            metadata={"from_state": "active", "to_state": "paused"},
        )
        events = worklog.event_log(conn, event_type="work_pause")
        assert len(events) >= 1
        last = events[0]
        assert last["work_item_id"] == wid
        meta = json.loads(last["metadata"])
        assert meta["from_state"] == "active"
        assert meta["to_state"] == "paused"
        conn.close()

    def test_log_transition_without_work_item(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.log_transition(
            conn, "work", work_item_id=None,
            repo_path="/tmp/test-repo",
            metadata={"from_state": "idle", "to_state": "scaffolded"},
        )
        events = worklog.event_log(conn, event_type="work")
        assert len(events) >= 1
        assert events[0]["work_item_id"] is None
        conn.close()

    def test_log_transition_merges_caller_metadata(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.log_transition(
            conn, "merge_pass", repo_path="/tmp/test-repo",
            metadata={
                "from_state": "closing:pushed",
                "to_state": "closing:merged",
                "landed_sha": "abc123",
            },
        )
        events = worklog.event_log(conn, event_type="merge_pass")
        meta = json.loads(events[0]["metadata"])
        assert meta["landed_sha"] == "abc123"
        assert meta["from_state"] == "closing:pushed"
        conn.close()


class TestIssueEvents:
    def _setup(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.ensure_repo(conn, "/repo/engine")
        wid = worklog.record_work_start(
            conn, "issue-42-spi", "/repo/engine",
            issue_number=42, issue_repo="org/engine",
        )
        return conn, wid

    def test_record_issue_activate(self, tmp_path):
        conn, wid = self._setup(tmp_path)
        worklog.record_issue_activate(conn, "issue-42-spi", "/repo/engine", 42, "org/engine")
        events = worklog.event_log(conn, event_type="issue-activate")
        assert len(events) == 1
        meta = json.loads(events[0]["metadata"])
        assert meta["issue_number"] == 42
        assert meta["issue_repo"] == "org/engine"
        conn.close()

    def test_record_issue_complete(self, tmp_path):
        conn, wid = self._setup(tmp_path)
        worklog.record_issue_complete(conn, "issue-42-spi", "/repo/engine", 42, "org/engine")
        events = worklog.event_log(conn, event_type="issue-complete")
        assert len(events) == 1
        meta = json.loads(events[0]["metadata"])
        assert meta["issue_number"] == 42
        conn.close()

    def test_issue_complete_updates_work_item_issues(self, tmp_path):
        conn, wid = self._setup(tmp_path)
        worklog.record_issue_complete(conn, "issue-42-spi", "/repo/engine", 108, "org/engine")
        rows = conn.execute(
            "SELECT * FROM work_item_issues WHERE issue_number=108"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["is_primary"] == 0
        conn.close()

    def test_issue_complete_deduplicates_work_item_issues(self, tmp_path):
        conn, wid = self._setup(tmp_path)
        worklog.record_issue_complete(conn, "issue-42-spi", "/repo/engine", 42, "org/engine")
        rows = conn.execute(
            "SELECT * FROM work_item_issues WHERE issue_number=42"
        ).fetchall()
        assert len(rows) == 1  # not duplicated

    def test_issue_activate_on_unknown_branch_is_nonfatal(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        result = worklog.record_issue_activate(conn, "nonexistent", "/repo", 42, "org/r")
        assert result is None
        conn.close()


class TestReserveSlotNumber:
    def test_first_slot_returns_1(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        num = worklog.reserve_slot_number(conn, "/family/root")
        assert num == 1
        conn.close()

    def test_increments_from_existing(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.reserve_slot_number(conn, "/family/root")
        num = worklog.reserve_slot_number(conn, "/family/root")
        assert num == 2
        conn.close()

    def test_inserts_pending_row(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        num = worklog.reserve_slot_number(conn, "/family/root")
        row = conn.execute(
            "SELECT state FROM slots WHERE slot_number=? AND family_root=?",
            (num, worklog._norm("/family/root")),
        ).fetchone()
        assert row["state"] == "pending"
        conn.close()

    def test_different_families_independent(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.reserve_slot_number(conn, "/family/a")
        worklog.reserve_slot_number(conn, "/family/a")
        num = worklog.reserve_slot_number(conn, "/family/b")
        assert num == 1
        conn.close()

    def test_skips_over_existing_numbers(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (?, ?, 'archived', '2026-01-01')",
            (50, worklog._norm("/family/root")),
        )
        conn.commit()
        num = worklog.reserve_slot_number(conn, "/family/root")
        assert num == 51
        conn.close()

    def test_skips_over_pending_numbers(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        worklog.reserve_slot_number(conn, "/family/root")
        num = worklog.reserve_slot_number(conn, "/family/root")
        assert num == 2
        conn.close()


class TestEnsureRepoStrict:
    def test_inserts_new_repo(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        repo_id = worklog._ensure_repo_strict(conn, "/path/to/repo")
        assert repo_id is not None
        row = conn.execute("SELECT path FROM repos WHERE id=?", (repo_id,)).fetchone()
        assert row["path"] == worklog._norm("/path/to/repo")
        conn.close()

    def test_returns_existing_repo_id(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        id1 = worklog._ensure_repo_strict(conn, "/path/to/repo")
        id2 = worklog._ensure_repo_strict(conn, "/path/to/repo")
        assert id1 == id2
        conn.close()

    def test_raises_on_closed_connection(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        conn.close()
        with pytest.raises(Exception):
            worklog._ensure_repo_strict(conn, "/path/to/repo")


class TestConfirmSlotCreate:
    def test_transitions_pending_to_active(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        num = worklog.reserve_slot_number(conn, "/family")
        sid = worklog.confirm_slot_create(
            conn, num, "/family",
            repos=["/family/engine"],
            branch="issue-42-test",
            issue_number=42,
            issue_repo="Org/repo",
        )
        row = conn.execute("SELECT state FROM slots WHERE id=?", (sid,)).fetchone()
        assert row["state"] == "active"
        conn.close()

    def test_creates_work_items(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        num = worklog.reserve_slot_number(conn, "/family")
        sid = worklog.confirm_slot_create(
            conn, num, "/family",
            repos=["/family/engine", "/family/app"],
            branch="issue-42-test",
            issue_number=42,
            issue_repo="Org/repo",
        )
        rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_items WHERE slot_id=?", (sid,)
        ).fetchone()
        assert rows["cnt"] == 2
        conn.close()

    def test_creates_issue_linkages(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        num = worklog.reserve_slot_number(conn, "/family")
        sid = worklog.confirm_slot_create(
            conn, num, "/family",
            repos=["/family/engine"],
            branch="issue-42-test",
            issue_number=42,
            issue_repo="Org/repo",
            covers="42,43",
        )
        rows = conn.execute(
            "SELECT issue_number, is_primary FROM work_item_issues "
            "ORDER BY issue_number"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["issue_number"] == 42
        assert rows[0]["is_primary"] == 1
        assert rows[1]["issue_number"] == 43
        assert rows[1]["is_primary"] == 0
        conn.close()

    def test_raises_if_no_pending_slot(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        with pytest.raises(ValueError, match="No pending slot"):
            worklog.confirm_slot_create(
                conn, 999, "/family",
                repos=["/family/engine"],
                branch="test",
                issue_number=1,
                issue_repo="Org/repo",
            )
        conn.close()

    def test_logs_slot_create_event(self, tmp_path):
        conn = worklog.connect(str(tmp_path / "wl.db"))
        num = worklog.reserve_slot_number(conn, "/family")
        sid = worklog.confirm_slot_create(
            conn, num, "/family",
            repos=["/family/engine"],
            branch="issue-42-test",
            issue_number=42,
            issue_repo="Org/repo",
        )
        events = conn.execute(
            "SELECT event_type FROM events WHERE slot_id=?", (sid,)
        ).fetchall()
        assert any(e["event_type"] == "slot-create" for e in events)
        conn.close()


class TestV2Migration:
    def test_v2_tables_created(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn = worklog.connect(str(db))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        assert "issue_enrichment" in tables
        assert "trajectory_notes" in tables
        assert "github_issue_cache" in tables
        conn.close()

    def test_v2_schema_version(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn = worklog.connect(str(db))
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 2
        conn.close()

    def test_v1_to_v2_upgrade(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(worklog.SCHEMA_V1)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.execute(
            "INSERT INTO repos (path) VALUES (?)", ("/test/repo",)
        )
        conn.commit()
        conn.close()
        conn = worklog.connect(str(db))
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 2
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        assert "issue_enrichment" in tables
        assert "trajectory_notes" in tables
        assert "github_issue_cache" in tables
        row = conn.execute("SELECT path FROM repos").fetchone()
        assert row[0] == "/test/repo"
        conn.close()

    def test_v2_indexes_created(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn = worklog.connect(str(db))
        indexes = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name"
        ).fetchall()]
        assert "idx_cache_repo" in indexes
        assert "idx_cache_staleness" in indexes
        assert "idx_enrichment_role" in indexes
        assert "idx_enrichment_decay" in indexes
        assert "idx_enrichment_readiness" in indexes
        assert "idx_trajectory_issue" in indexes
        conn.close()
