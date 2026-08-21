"""Tests for scripts/reconcile_slots.py — three-phase reconciliation."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))

import worklog
import reconcile_slots


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(worklog, "DEFAULT_DB", str(db_path))
    conn = worklog.connect(str(db_path))
    yield conn
    conn.close()


class TestAudit:
    def test_detects_ghost(self, tmp_path, db):
        family = tmp_path / "family"
        ghost = family / "slots" / "1"
        ghost.mkdir(parents=True)
        (ghost / ".m2").mkdir()

        divergences = reconcile_slots.audit(family)
        assert len(divergences) == 1
        assert divergences[0]["class"] == "ghost"
        assert divergences[0]["slot"] == 1

    def test_detects_db_only(self, tmp_path, db):
        family = tmp_path / "family"
        (family / "slots").mkdir(parents=True)
        norm = worklog._norm(str(family))
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (99, ?, 'active', '2026-01-01')", (norm,),
        )
        db.commit()

        divergences = reconcile_slots.audit(family)
        assert any(d["class"] == "db-only" and d["slot"] == 99 for d in divergences)

    def test_detects_disk_only(self, tmp_path, db):
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")

        divergences = reconcile_slots.audit(family)
        assert any(d["class"] == "disk-only" and d["slot"] == 1 for d in divergences)

    def test_detects_state_mismatch(self, tmp_path, db):
        family = tmp_path / "family"
        attic = family / "slots" / "attic" / "1"
        attic.mkdir(parents=True)
        (attic / ".slot").write_text("# Slot 1 — test\n")
        norm = worklog._norm(str(family))
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'active', '2026-01-01')", (norm,),
        )
        db.commit()

        divergences = reconcile_slots.audit(family)
        assert any(d["class"] == "state-mismatch" and d["slot"] == 1 for d in divergences)

    def test_clean_returns_empty(self, tmp_path, db):
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")
        norm = worklog._norm(str(family))
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'active', '2026-01-01')", (norm,),
        )
        db.commit()

        divergences = reconcile_slots.audit(family)
        assert divergences == []


class TestStrategy:
    def test_ghost_proposes_quarantine(self):
        divergences = [{"slot": 3, "class": "ghost", "disk_path": "/slots/3",
                        "disk_contents": ["aml"], "db_state": None, "detail": ""}]
        actions = reconcile_slots.strategy(divergences)
        assert actions[0]["action"] == "quarantine"

    def test_db_only_proposes_remove_record(self):
        divergences = [{"slot": 99, "class": "db-only", "db_state": "active",
                        "db_created": "2026-01-01", "detail": ""}]
        actions = reconcile_slots.strategy(divergences)
        assert actions[0]["action"] == "remove_db_record"

    def test_disk_only_proposes_backfill(self):
        divergences = [{"slot": 1, "class": "disk-only", "disk_path": "/slots/1",
                        "disk_location": "active", "has_landed": False, "detail": ""}]
        actions = reconcile_slots.strategy(divergences)
        assert actions[0]["action"] == "backfill_db"

    def test_state_mismatch_proposes_update_db(self):
        divergences = [{"slot": 1, "class": "state-mismatch", "disk_path": "/attic/1",
                        "disk_state": "archived", "db_state": "active", "detail": ""}]
        actions = reconcile_slots.strategy(divergences)
        assert actions[0]["action"] == "update_db_state"
        assert actions[0]["new_state"] == "archived"


class TestExecute:
    def test_quarantine_moves_to_quarantine_dir(self, tmp_path, db):
        family = tmp_path / "family"
        ghost = family / "slots" / "3"
        ghost.mkdir(parents=True)
        (ghost / "aml").mkdir()
        (ghost / "aml" / "file.txt").write_text("data")

        actions = [{"slot": 3, "action": "quarantine", "source": str(ghost),
                     "detail": "", "risk": "low"}]
        results = reconcile_slots.execute(actions, family)

        assert not ghost.exists()
        quarantine = family / "slots" / "quarantine" / "3"
        assert quarantine.exists()
        assert (quarantine / "aml" / "file.txt").read_text() == "data"
        assert results[0]["status"] == "done"

    def test_quarantine_skips_if_dest_exists(self, tmp_path, db):
        family = tmp_path / "family"
        ghost = family / "slots" / "3"
        ghost.mkdir(parents=True)
        quarantine = family / "slots" / "quarantine" / "3"
        quarantine.mkdir(parents=True)

        actions = [{"slot": 3, "action": "quarantine", "source": str(ghost),
                     "detail": "", "risk": "low"}]
        results = reconcile_slots.execute(actions, family)
        assert results[0]["status"] == "skipped"

    def test_remove_db_record(self, tmp_path, db):
        family = tmp_path / "family"
        norm = worklog._norm(str(family))
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (99, ?, 'active', '2026-01-01')", (norm,),
        )
        db.commit()

        actions = [{"slot": 99, "action": "remove_db_record",
                     "db_state": "active", "detail": "", "risk": "low"}]
        results = reconcile_slots.execute(actions, family)
        assert results[0]["status"] == "done"
        row = db.execute(
            "SELECT id FROM slots WHERE slot_number=99 AND family_root=?", (norm,)
        ).fetchone()
        assert row is None

    def test_backfill_db(self, tmp_path, db):
        family = tmp_path / "family"
        actions = [{"slot": 1, "action": "backfill_db", "disk_path": str(family / "slots/1"),
                     "disk_location": "active", "detail": "", "risk": "low"}]
        results = reconcile_slots.execute(actions, family)
        assert results[0]["status"] == "done"
        norm = worklog._norm(str(family))
        row = db.execute(
            "SELECT state FROM slots WHERE slot_number=1 AND family_root=?", (norm,)
        ).fetchone()
        assert row["state"] == "active"

    def test_update_db_state(self, tmp_path, db):
        family = tmp_path / "family"
        norm = worklog._norm(str(family))
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'active', '2026-01-01')", (norm,),
        )
        db.commit()

        actions = [{"slot": 1, "action": "update_db_state", "new_state": "archived",
                     "old_state": "active", "detail": "", "risk": "low"}]
        results = reconcile_slots.execute(actions, family)
        assert results[0]["status"] == "done"
        row = db.execute(
            "SELECT state FROM slots WHERE slot_number=1 AND family_root=?", (norm,)
        ).fetchone()
        assert row["state"] == "archived"


class TestParseSlotFile:
    def test_parses_standard_slot(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text(
            "# Slot 124 — issue-139-eidos-annotations\n\n"
            "## Issue\ncasehubio/eidos#139\nCovers: 139\n\n"
            "## Repos\n- eidos (primary)\n\n"
            "## Created\n2026-08-15, branch: issue-139-eidos-annotations\n"
        )
        result = reconcile_slots._parse_slot_file(slot_dir)
        assert result["issue_repo"] == "casehubio/eidos"
        assert result["issue_number"] == 139
        assert result["branch"] == "issue-139-eidos-annotations"
        assert result["primary_repo"] == "eidos"

    def test_parses_multi_repo_slot(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text(
            "# Slot 118\n\n## Issue\ncasehubio/engine#110\nCovers: 110,114\n\n"
            "## Repos\n- engine (primary)\n- blocks\n\n"
            "## Created\n2026-08-12, branch: issue-110-goal-decomposition\n"
        )
        result = reconcile_slots._parse_slot_file(slot_dir)
        assert result["issue_repo"] == "casehubio/engine"
        assert result["issue_number"] == 110
        assert result["primary_repo"] == "engine"

    def test_returns_none_without_slot_file(self, tmp_path):
        assert reconcile_slots._parse_slot_file(tmp_path) is None

    def test_returns_none_without_issue(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("# Slot 1\nno issue here\n")
        assert reconcile_slots._parse_slot_file(slot_dir) is None


class TestCheckGitHub:
    def _make_slot(self, family, num, issue_repo, issue_num, branch="main"):
        slot_dir = family / "slots" / str(num)
        slot_dir.mkdir(parents=True, exist_ok=True)
        (slot_dir / ".slot").write_text(
            f"# Slot {num}\n\n## Issue\n{issue_repo}#{issue_num}\n\n"
            f"## Repos\n- engine (primary)\n\n"
            f"## Created\n2026-01-01, branch: {branch}\n"
        )
        return slot_dir

    def test_detects_closed_issue(self, tmp_path, db):
        family = tmp_path / "family"
        self._make_slot(family, 1, "org/repo", 42, "issue-42")
        norm = worklog._norm(str(family))
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'active', '2026-01-01')", (norm,),
        )
        db.commit()

        def mock_run(cmd, **kwargs):
            if "gh" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="CLOSED\n", stderr="")
            if "fetch" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "log" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            findings = reconcile_slots.check_github(family)

        assert len(findings) == 1
        assert findings[0]["slot"] == 1
        assert findings[0]["resolution"] == "obsolete"

    def test_skips_open_issue(self, tmp_path, db):
        family = tmp_path / "family"
        self._make_slot(family, 1, "org/repo", 42, "issue-42")
        norm = worklog._norm(str(family))
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'active', '2026-01-01')", (norm,),
        )
        db.commit()

        def mock_run(cmd, **kwargs):
            if "gh" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="OPEN\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            findings = reconcile_slots.check_github(family)

        assert len(findings) == 0

    def test_skips_already_archived(self, tmp_path, db):
        family = tmp_path / "family"
        self._make_slot(family, 1, "org/repo", 42, "issue-42")
        norm = worklog._norm(str(family))
        db.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at, archived_at) "
            "VALUES (1, ?, 'archived', '2026-01-01', '2026-01-02')", (norm,),
        )
        db.commit()

        def mock_run(cmd, **kwargs):
            if "gh" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="CLOSED\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            findings = reconcile_slots.check_github(family)

        assert len(findings) == 0


class TestExecuteGitHubActions:
    def test_archives_superseded_slot(self, tmp_path, db):
        family = tmp_path / "family"
        slot_dir = family / "slots" / "10"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 10\n")
        norm = worklog._norm(str(family))
        worklog.ensure_repo(db, "/repo/engine", family_root=str(family))
        worklog.record_slot_create(db, 10, str(family), ["/repo/engine"],
                                   "issue-42", 42, "org/engine")

        findings = [{
            "slot": 10, "issue_repo": "org/engine", "issue_number": 42,
            "branch": "issue-42", "resolution": "superseded",
            "evidence": "1 commit on main", "disk_path": str(slot_dir),
        }]
        results = reconcile_slots.execute_github_actions(findings, family)

        assert results[0]["status"] == "done"
        assert results[0]["resolution"] == "superseded"
        assert not slot_dir.exists()
        assert (family / "slots" / "attic" / "10").exists()

        row = db.execute(
            "SELECT state, resolution FROM slots WHERE slot_number=10 AND family_root=?",
            (norm,),
        ).fetchone()
        assert row["state"] == "archived"
        assert row["resolution"] == "superseded"

    def test_skips_needs_review(self, tmp_path, db):
        family = tmp_path / "family"
        findings = [{
            "slot": 11, "issue_repo": "org/engine", "issue_number": 99,
            "branch": "issue-99", "resolution": "needs-review",
            "evidence": "unmerged work", "disk_path": str(family / "slots/11"),
        }]
        results = reconcile_slots.execute_github_actions(findings, family)
        assert results[0]["status"] == "needs-review"
