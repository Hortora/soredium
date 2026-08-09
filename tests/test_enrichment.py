"""Tests for scripts/enrichment.py"""

import datetime
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import worklog
import enrichment


def _conn(tmp_path):
    return worklog.connect(str(tmp_path / "worklog.db"))


class TestUpsertEnrichment:
    def test_insert_new(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_enrichment(
            conn, 42, "Hortora/soredium",
            strategic_role="quick-win", readiness="ready",
        )
        row = conn.execute(
            "SELECT * FROM issue_enrichment WHERE issue_number=42"
        ).fetchone()
        assert row is not None
        assert row["strategic_role"] == "quick-win"
        assert row["readiness"] == "ready"
        assert row["updated_at"] is not None
        conn.close()

    def test_merge_existing(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_enrichment(
            conn, 42, "Hortora/soredium",
            strategic_role="quick-win", readiness="ready",
        )
        enrichment.upsert_enrichment(
            conn, 42, "Hortora/soredium",
            decay="compounding",
        )
        row = conn.execute(
            "SELECT * FROM issue_enrichment WHERE issue_number=42"
        ).fetchone()
        assert row["strategic_role"] == "quick-win"
        assert row["readiness"] == "ready"
        assert row["decay"] == "compounding"
        conn.close()

    def test_validates_strategic_role(self, tmp_path):
        conn = _conn(tmp_path)
        with pytest.raises(ValueError, match="strategic_role"):
            enrichment.upsert_enrichment(
                conn, 42, "Hortora/soredium",
                strategic_role="invalid-role",
            )
        conn.close()

    def test_validates_readiness(self, tmp_path):
        conn = _conn(tmp_path)
        with pytest.raises(ValueError, match="readiness"):
            enrichment.upsert_enrichment(
                conn, 42, "Hortora/soredium",
                readiness="invalid",
            )
        conn.close()

    def test_validates_decay(self, tmp_path):
        conn = _conn(tmp_path)
        with pytest.raises(ValueError, match="decay"):
            enrichment.upsert_enrichment(
                conn, 42, "Hortora/soredium",
                decay="invalid",
            )
        conn.close()

    def test_validates_blast_radius(self, tmp_path):
        conn = _conn(tmp_path)
        with pytest.raises(ValueError, match="blast_radius"):
            enrichment.upsert_enrichment(
                conn, 42, "Hortora/soredium",
                blast_radius="invalid",
            )
        conn.close()

    def test_cohesion_is_freetext(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_enrichment(
            conn, 42, "Hortora/soredium",
            cohesion="lifecycle",
        )
        row = conn.execute(
            "SELECT cohesion FROM issue_enrichment WHERE issue_number=42"
        ).fetchone()
        assert row["cohesion"] == "lifecycle"
        conn.close()


class TestGetEnrichment:
    def test_returns_dict(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_enrichment(
            conn, 42, "Hortora/soredium",
            strategic_role="quick-win",
        )
        result = enrichment.get_enrichment(conn, 42, "Hortora/soredium")
        assert result is not None
        assert result["strategic_role"] == "quick-win"
        assert result["issue_number"] == 42
        conn.close()

    def test_returns_none_when_missing(self, tmp_path):
        conn = _conn(tmp_path)
        result = enrichment.get_enrichment(conn, 999, "Hortora/soredium")
        assert result is None
        conn.close()


class TestListEnrichments:
    def test_lists_all_for_repo(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_enrichment(conn, 1, "org/repo", strategic_role="quick-win")
        enrichment.upsert_enrichment(conn, 2, "org/repo", strategic_role="load-bearing")
        enrichment.upsert_enrichment(conn, 3, "org/other", strategic_role="quick-win")
        result = enrichment.list_enrichments(conn, "org/repo")
        assert len(result) == 2
        nums = {r["issue_number"] for r in result}
        assert nums == {1, 2}
        conn.close()


class TestTrajectoryNotes:
    def test_append_and_get(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.append_trajectory(conn, 42, "org/repo", "Schema landed, #43 is now ready")
        notes = enrichment.get_trajectory(conn, 42, "org/repo")
        assert len(notes) == 1
        assert notes[0]["note"] == "Schema landed, #43 is now ready"
        assert notes[0]["created_at"] is not None
        conn.close()

    def test_append_with_source_branch(self, tmp_path):
        conn = _conn(tmp_path)
        rid = enrichment.append_trajectory(
            conn, 42, "org/repo", "note text",
            source_branch="issue-42-schema",
        )
        assert rid is not None
        notes = enrichment.get_trajectory(conn, 42, "org/repo")
        assert notes[0]["source_branch"] == "issue-42-schema"
        conn.close()

    def test_accumulates_multiple_notes(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.append_trajectory(conn, 42, "org/repo", "first note")
        enrichment.append_trajectory(conn, 42, "org/repo", "second note")
        enrichment.append_trajectory(conn, 42, "org/repo", "third note")
        notes = enrichment.get_trajectory(conn, 42, "org/repo")
        assert len(notes) == 3
        assert notes[0]["note"] == "third note"
        assert notes[2]["note"] == "first note"
        conn.close()

    def test_limit(self, tmp_path):
        conn = _conn(tmp_path)
        for i in range(5):
            enrichment.append_trajectory(conn, 42, "org/repo", f"note {i}")
        notes = enrichment.get_trajectory(conn, 42, "org/repo", limit=2)
        assert len(notes) == 2
        conn.close()

    def test_scoped_to_issue(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.append_trajectory(conn, 42, "org/repo", "for 42")
        enrichment.append_trajectory(conn, 43, "org/repo", "for 43")
        notes = enrichment.get_trajectory(conn, 42, "org/repo")
        assert len(notes) == 1
        assert notes[0]["note"] == "for 42"
        conn.close()


class TestCachedIssueCRUD:
    def test_upsert_and_get(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_cached_issue(
            conn, 42, "org/repo",
            title="Fix bug", state="OPEN",
            labels=["enhancement", "scale:S"], body="Description",
        )
        result = enrichment.get_cached_issue(conn, 42, "org/repo")
        assert result is not None
        assert result["title"] == "Fix bug"
        assert result["state"] == "OPEN"
        assert json.loads(result["labels"]) == ["enhancement", "scale:S"]
        assert result["cached_at"] is not None
        conn.close()

    def test_upsert_replaces_existing(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_cached_issue(
            conn, 42, "org/repo",
            title="Old", state="OPEN", labels=[], body="",
        )
        enrichment.upsert_cached_issue(
            conn, 42, "org/repo",
            title="New", state="OPEN", labels=[], body="",
        )
        result = enrichment.get_cached_issue(conn, 42, "org/repo")
        assert result["title"] == "New"
        conn.close()

    def test_get_returns_none_when_missing(self, tmp_path):
        conn = _conn(tmp_path)
        result = enrichment.get_cached_issue(conn, 999, "org/repo")
        assert result is None
        conn.close()


class TestCacheFreshness:
    def test_fresh_when_within_ttl(self, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_cached_issue(
            conn, 42, "org/repo",
            title="t", state="OPEN", labels=[], body="",
        )
        assert enrichment.is_cache_fresh(conn, "org/repo", ttl_seconds=300)
        conn.close()

    def test_stale_when_no_rows(self, tmp_path):
        conn = _conn(tmp_path)
        assert not enrichment.is_cache_fresh(conn, "org/repo")
        conn.close()

    def test_stale_when_expired(self, tmp_path):
        conn = _conn(tmp_path)
        past = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=600)
        ).isoformat()
        conn.execute(
            "INSERT INTO github_issue_cache "
            "(issue_number, issue_repo, title, state, labels, body, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (42, "org/repo", "t", "OPEN", "[]", "", past),
        )
        conn.commit()
        assert not enrichment.is_cache_fresh(conn, "org/repo", ttl_seconds=300)
        conn.close()


class TestRefreshCache:
    def _gh_response(self):
        return json.dumps([
            {"number": 1, "title": "Issue 1", "state": "OPEN",
             "labels": [{"name": "enhancement"}], "body": "body1"},
            {"number": 2, "title": "Issue 2", "state": "OPEN",
             "labels": [{"name": "bug"}, {"name": "scale:S"}], "body": "body2"},
        ])

    @patch("enrichment.subprocess.run")
    def test_refresh_populates_cache(self, mock_run, tmp_path):
        conn = _conn(tmp_path)
        mock_run.return_value = MagicMock(
            returncode=0, stdout=self._gh_response(),
        )
        count = enrichment.refresh_cache(conn, "org/repo", ttl_seconds=0)
        assert count == 2
        r1 = enrichment.get_cached_issue(conn, 1, "org/repo")
        assert r1["title"] == "Issue 1"
        assert json.loads(r1["labels"]) == ["enhancement"]
        r2 = enrichment.get_cached_issue(conn, 2, "org/repo")
        assert json.loads(r2["labels"]) == ["bug", "scale:S"]
        conn.close()

    @patch("enrichment.subprocess.run")
    def test_refresh_skips_when_fresh(self, mock_run, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_cached_issue(
            conn, 1, "org/repo", title="t", state="OPEN", labels=[], body="",
        )
        count = enrichment.refresh_cache(conn, "org/repo", ttl_seconds=9999)
        assert count == 0
        mock_run.assert_not_called()
        conn.close()

    @patch("enrichment.subprocess.run")
    def test_refresh_deletes_closed_issues(self, mock_run, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_cached_issue(
            conn, 99, "org/repo", title="old", state="OPEN", labels=[], body="",
        )
        mock_run.return_value = MagicMock(
            returncode=0, stdout=self._gh_response(),
        )
        enrichment.refresh_cache(conn, "org/repo", ttl_seconds=0)
        assert enrichment.get_cached_issue(conn, 99, "org/repo") is None
        conn.close()

    @patch("enrichment.subprocess.run")
    def test_refresh_preserves_cache_on_empty_response(self, mock_run, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_cached_issue(
            conn, 1, "org/repo", title="existing", state="OPEN", labels=[], body="",
        )
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        count = enrichment.refresh_cache(conn, "org/repo", ttl_seconds=0)
        assert count == 0
        assert enrichment.get_cached_issue(conn, 1, "org/repo") is not None
        conn.close()

    @patch("enrichment.subprocess.run")
    def test_refresh_handles_gh_failure(self, mock_run, tmp_path):
        conn = _conn(tmp_path)
        enrichment.upsert_cached_issue(
            conn, 1, "org/repo", title="existing", state="OPEN", labels=[], body="",
        )
        mock_run.side_effect = FileNotFoundError("gh not found")
        count = enrichment.refresh_cache(conn, "org/repo", ttl_seconds=0)
        assert count == 0
        assert enrichment.get_cached_issue(conn, 1, "org/repo") is not None
        conn.close()

    @patch("enrichment.subprocess.run")
    def test_refresh_handles_nonzero_exit(self, mock_run, tmp_path):
        conn = _conn(tmp_path)
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="auth error")
        count = enrichment.refresh_cache(conn, "org/repo", ttl_seconds=0)
        assert count == 0
        conn.close()


class TestWhatNext:
    def _seed(self, conn):
        enrichment.upsert_cached_issue(conn, 1, "org/repo", "Quick fix", "OPEN", ["scale:XS"], "")
        enrichment.upsert_cached_issue(conn, 2, "org/repo", "Big refactor", "OPEN", ["scale:L"], "")
        enrichment.upsert_cached_issue(conn, 3, "org/repo", "Urgent decay", "OPEN", [], "")
        enrichment.upsert_cached_issue(conn, 4, "org/repo", "Isolated task", "OPEN", [], "")
        enrichment.upsert_cached_issue(conn, 5, "org/repo", "Unenriched", "OPEN", [], "")
        enrichment.upsert_enrichment(conn, 1, "org/repo", strategic_role="quick-win", readiness="ready", decay="stable", blast_radius="isolated")
        enrichment.upsert_enrichment(conn, 2, "org/repo", strategic_role="load-bearing", readiness="ready", decay="stable", blast_radius="cross-cutting")
        enrichment.upsert_enrichment(conn, 3, "org/repo", strategic_role="consolidation", readiness="ready", decay="compounding", blast_radius="local")
        enrichment.upsert_enrichment(conn, 4, "org/repo", strategic_role="parallelizable", readiness="ready", decay="stable", blast_radius="isolated")
        enrichment.append_trajectory(conn, 1, "org/repo", "This unblocks #2")

    def test_general_returns_all_open(self, tmp_path):
        conn = _conn(tmp_path)
        self._seed(conn)
        results = enrichment.what_next(conn, "org/repo", mode="general")
        assert len(results) == 5
        assert all(r["issue_repo"] == "org/repo" for r in results)
        conn.close()

    def test_general_enriched_score_higher_than_unenriched(self, tmp_path):
        conn = _conn(tmp_path)
        self._seed(conn)
        results = enrichment.what_next(conn, "org/repo", mode="general")
        enriched_scores = [r["score"] for r in results if r["enriched"]]
        unenriched_scores = [r["score"] for r in results if not r["enriched"]]
        assert min(enriched_scores) > max(unenriched_scores)
        conn.close()

    def test_quick_wins_filters(self, tmp_path):
        conn = _conn(tmp_path)
        self._seed(conn)
        results = enrichment.what_next(conn, "org/repo", mode="quick-wins")
        assert len(results) >= 1
        assert all(r["strategic_role"] == "quick-win" for r in results if r["enriched"])
        conn.close()

    def test_compounding_filters(self, tmp_path):
        conn = _conn(tmp_path)
        self._seed(conn)
        results = enrichment.what_next(conn, "org/repo", mode="compounding")
        assert len(results) >= 1
        assert all(r["decay"] == "compounding" for r in results if r["enriched"])
        conn.close()

    def test_parallelizable_filters(self, tmp_path):
        conn = _conn(tmp_path)
        self._seed(conn)
        results = enrichment.what_next(conn, "org/repo", mode="parallelizable")
        enriched = [r for r in results if r["enriched"]]
        assert all(r["blast_radius"] == "isolated" for r in enriched)
        conn.close()

    def test_cohesion_filters(self, tmp_path):
        conn = _conn(tmp_path)
        self._seed(conn)
        enrichment.upsert_enrichment(conn, 1, "org/repo", cohesion="lifecycle")
        enrichment.upsert_enrichment(conn, 4, "org/repo", cohesion="lifecycle")
        results = enrichment.what_next(conn, "org/repo", mode="cohesion", cohesion_tag="lifecycle")
        enriched = [r for r in results if r["enriched"]]
        assert all(r["cohesion"] == "lifecycle" for r in enriched)
        conn.close()

    def test_limit(self, tmp_path):
        conn = _conn(tmp_path)
        self._seed(conn)
        results = enrichment.what_next(conn, "org/repo", mode="general", limit=2)
        assert len(results) == 2
        conn.close()

    def test_unenriched_flagged(self, tmp_path):
        conn = _conn(tmp_path)
        self._seed(conn)
        results = enrichment.what_next(conn, "org/repo", mode="general")
        issue5 = [r for r in results if r["issue_number"] == 5][0]
        assert issue5["enriched"] is False
        assert issue5["score"] == 0
        conn.close()

    def test_includes_recent_trajectory(self, tmp_path):
        conn = _conn(tmp_path)
        self._seed(conn)
        results = enrichment.what_next(conn, "org/repo", mode="general")
        issue1 = [r for r in results if r["issue_number"] == 1][0]
        assert issue1["recent_trajectory"] is not None
        conn.close()

    def test_invalid_mode_raises(self, tmp_path):
        conn = _conn(tmp_path)
        with pytest.raises(ValueError, match="mode"):
            enrichment.what_next(conn, "org/repo", mode="invalid")
        conn.close()


class TestCLI:
    def _run(self, *args, db_path=None):
        cmd = [sys.executable, str(Path(__file__).parent.parent / "scripts" / "enrichment.py")]
        cmd.extend(args)
        env = {**os.environ}
        if db_path:
            env["WORKLOG_DB"] = str(db_path)
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        return result

    def test_upsert_and_get(self, tmp_path):
        db = tmp_path / "worklog.db"
        worklog.connect(str(db)).close()
        r = self._run(
            "upsert", "--issue", "42", "--repo", "org/repo",
            "--role", "quick-win", "--readiness", "ready",
            db_path=db,
        )
        assert r.returncode == 0
        r = self._run("get", "--issue", "42", "--repo", "org/repo", db_path=db)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["strategic_role"] == "quick-win"

    def test_trajectory_subcommand(self, tmp_path):
        db = tmp_path / "worklog.db"
        worklog.connect(str(db)).close()
        r = self._run(
            "trajectory", "--issue", "42", "--repo", "org/repo",
            "--text", "Schema landed",
            db_path=db,
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["ok"] is True

    def test_list_subcommand(self, tmp_path):
        db = tmp_path / "worklog.db"
        conn = worklog.connect(str(db))
        enrichment.upsert_enrichment(conn, 1, "org/repo", strategic_role="quick-win")
        conn.close()
        r = self._run("list", "--repo", "org/repo", db_path=db)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 1

    def test_invalid_subcommand(self, tmp_path):
        r = self._run("bogus")
        assert r.returncode != 0

    def test_upsert_invalid_enum(self, tmp_path):
        db = tmp_path / "worklog.db"
        worklog.connect(str(db)).close()
        r = self._run(
            "upsert", "--issue", "42", "--repo", "org/repo",
            "--role", "invalid",
            db_path=db,
        )
        assert r.returncode == 1
