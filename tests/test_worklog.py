"""Tests for scripts/worklog.py"""

import json
import sys
from pathlib import Path

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
        assert ver == 1
        conn.close()

    def test_idempotent_connect(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn1 = worklog.connect(str(db))
        conn1.close()
        conn2 = worklog.connect(str(db))
        ver = conn2.execute("PRAGMA user_version").fetchone()[0]
        assert ver == 1
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
