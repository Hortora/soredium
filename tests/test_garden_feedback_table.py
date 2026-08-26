"""Tests for scripts/garden_feedback_table.py"""

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import garden_feedback_table as gft


@pytest.fixture
def retrieval_db(tmp_path, monkeypatch):
    db_path = tmp_path / "retrieval-tracking.db"
    monkeypatch.setattr(gft, "RETRIEVAL_DB", db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE retrieval_records (
            retrieval_id TEXT PRIMARY KEY,
            query_text TEXT,
            expanded_text TEXT,
            tenant_id TEXT,
            corpus_name TEXT,
            max_results INTEGER,
            timestamp TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE retrieved_documents (
            retrieval_id TEXT,
            source_document_id TEXT,
            relevance_score REAL,
            FOREIGN KEY (retrieval_id) REFERENCES retrieval_records(retrieval_id)
        )
    """)
    conn.execute("""
        CREATE TABLE retrieval_feedback (
            retrieval_id TEXT,
            source_document_id TEXT,
            outcome TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    yield conn
    conn.close()


def _insert_retrieval(conn, retrieval_id, doc_path, timestamp=None, query="test query"):
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO retrieval_records (retrieval_id, query_text, timestamp) VALUES (?, ?, ?)",
        (retrieval_id, query, timestamp),
    )
    conn.execute(
        "INSERT INTO retrieved_documents (retrieval_id, source_document_id, relevance_score) VALUES (?, ?, ?)",
        (retrieval_id, doc_path, -1.0),
    )
    conn.commit()


class TestGetRecentRetrievals:
    def test_returns_recent_entries(self, retrieval_db):
        now = datetime.now(timezone.utc).isoformat()
        _insert_retrieval(retrieval_db, "r1", "tools/GE-20260826-aaaaaa.md", now)
        results = gft._get_recent_retrievals(4)
        assert len(results) == 1
        assert results[0]["ge_id"] == "GE-20260826-aaaaaa"

    def test_filters_old_entries(self, retrieval_db):
        old = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
        _insert_retrieval(retrieval_db, "r1", "tools/GE-20260826-aaaaaa.md", old)
        results = gft._get_recent_retrievals(4)
        assert len(results) == 0

    def test_deduplicates_same_doc(self, retrieval_db):
        now = datetime.now(timezone.utc).isoformat()
        _insert_retrieval(retrieval_db, "r1", "tools/GE-20260826-aaaaaa.md", now)
        _insert_retrieval(retrieval_db, "r2", "tools/GE-20260826-aaaaaa.md", now)
        results = gft._get_recent_retrievals(4)
        assert len(results) == 1

    def test_returns_empty_when_no_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gft, "RETRIEVAL_DB", tmp_path / "nonexistent.db")
        assert gft._get_recent_retrievals(4) == []

    def test_skips_non_ge_documents(self, retrieval_db):
        now = datetime.now(timezone.utc).isoformat()
        _insert_retrieval(retrieval_db, "r1", "approaches/testing.md", now)
        results = gft._get_recent_retrievals(4)
        assert len(results) == 0


class TestCheckVersionMatch:
    def test_detects_mismatch(self):
        result = gft._check_version_match("quarkus: 3.34.2", {"quarkus": "3.36.1"})
        assert "3.34.2" in result
        assert "3.36.1" in result

    def test_no_flag_when_matching(self):
        result = gft._check_version_match("quarkus: 3.36.1", {"quarkus": "3.36.1"})
        assert result is None

    def test_no_flag_when_tech_not_in_project(self):
        result = gft._check_version_match("quarkus: 3.34.2", {"jdk": "21"})
        assert result is None

    def test_handles_empty_verified_on(self):
        assert gft._check_version_match("", {"quarkus": "3.36.1"}) is None

    def test_handles_multiple_versions(self):
        result = gft._check_version_match(
            "quarkus: 3.34.2, jdk: 21",
            {"quarkus": "3.36.1", "jdk": "21"},
        )
        assert "3.34.2" in result
        assert "3.36.1" in result


class TestCheckStaleness:
    def test_detects_stale_entry(self):
        result = gft._check_staleness({
            "submitted": "2024-01-01",
            "staleness_threshold": "365",
        })
        assert result is not None
        assert "stale" in result

    def test_no_flag_for_fresh_entry(self):
        today = datetime.now().strftime("%Y-%m-%d")
        result = gft._check_staleness({
            "submitted": today,
            "staleness_threshold": "730",
        })
        assert result is None

    def test_flags_unreviewed_old_entry(self):
        six_months_ago = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        result = gft._check_staleness({
            "submitted": six_months_ago,
            "staleness_threshold": "730",
        })
        assert result is not None
        assert "not reviewed" in result

    def test_uses_last_reviewed_over_submitted(self):
        today = datetime.now().strftime("%Y-%m-%d")
        result = gft._check_staleness({
            "submitted": "2024-01-01",
            "last_reviewed": today,
            "staleness_threshold": "730",
        })
        assert result is None


class TestParseStackVersions:
    def test_reads_pom_xml(self, tmp_path):
        (tmp_path / "pom.xml").write_text("""<project>
            <properties>
                <quarkus.platform.version>3.36.1</quarkus.platform.version>
                <maven.compiler.release>21</maven.compiler.release>
            </properties>
        </project>""")
        versions = gft._parse_stack_versions(str(tmp_path))
        assert versions["quarkus"] == "3.36.1"
        assert versions["jdk"] == "21"

    def test_reads_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18.2.0"},
            "devDependencies": {"typescript": "~5.3.2"},
        }))
        versions = gft._parse_stack_versions(str(tmp_path))
        assert versions["react"] == "18.2.0"
        assert versions["typescript"] == "5.3.2"

    def test_returns_empty_for_no_files(self, tmp_path):
        assert gft._parse_stack_versions(str(tmp_path)) == {}


class TestBuildTable:
    def test_returns_empty_when_no_retrievals(self, retrieval_db, tmp_path):
        data = gft.build_table(str(tmp_path), hours=4)
        assert data["entries"] == []

    def test_flags_missing_verified_on_for_gotchas(self, retrieval_db, tmp_path, monkeypatch):
        now = datetime.now(timezone.utc).isoformat()
        _insert_retrieval(retrieval_db, "r1", "tools/GE-20260826-bbbbbb.md", now)
        monkeypatch.setattr(gft, "_read_entry_frontmatter", lambda p: {
            "_title": "Some gotcha",
            "type": "gotcha",
            "submitted": "2026-08-01",
            "staleness_threshold": "730",
        })
        data = gft.build_table(str(tmp_path), hours=4)
        assert len(data["entries"]) == 1
        flags = data["entries"][0]["flags"]
        assert any("unverified" in f for f in flags)

    def test_flags_version_mismatch(self, retrieval_db, tmp_path, monkeypatch):
        now = datetime.now(timezone.utc).isoformat()
        _insert_retrieval(retrieval_db, "r1", "jvm/GE-20260826-cccccc.md", now)
        monkeypatch.setattr(gft, "_read_entry_frontmatter", lambda p: {
            "_title": "Quarkus gotcha",
            "type": "gotcha",
            "verified_on": "quarkus: 3.34.2",
            "submitted": "2026-08-01",
            "staleness_threshold": "730",
        })
        (tmp_path / "pom.xml").write_text(
            "<project><properties>"
            "<quarkus.platform.version>3.36.1</quarkus.platform.version>"
            "</properties></project>"
        )
        data = gft.build_table(str(tmp_path), hours=4)
        flags = data["entries"][0]["flags"]
        assert any("3.34.2" in f and "3.36.1" in f for f in flags)

    def test_no_flags_for_clean_technique(self, retrieval_db, tmp_path, monkeypatch):
        now = datetime.now(timezone.utc).isoformat()
        _insert_retrieval(retrieval_db, "r1", "tools/GE-20260826-dddddd.md", now)
        today = datetime.now().strftime("%Y-%m-%d")
        monkeypatch.setattr(gft, "_read_entry_frontmatter", lambda p: {
            "_title": "Clean technique",
            "type": "technique",
            "submitted": today,
            "staleness_threshold": "730",
        })
        data = gft.build_table(str(tmp_path), hours=4)
        assert data["entries"][0]["flags"] == []


class TestFormatTable:
    def test_no_entries(self):
        output = gft.format_table({"entries": [], "project_stack": {}, "hours": 4})
        assert "NO_ENTRIES=true" in output

    def test_formats_with_flags(self):
        data = {
            "entries": [{
                "ge_id": "GE-20260826-aaaaaa",
                "doc_path": "tools/GE-20260826-aaaaaa.md",
                "title": "Test entry",
                "type": "gotcha",
                "flags": ["⚠️ verified on quarkus 3.34.2, project uses 3.36.1"],
                "default_outcome": "RELEVANT",
            }],
            "project_stack": {"quarkus": "3.36.1"},
            "hours": 4,
        }
        output = gft.format_table(data)
        assert "ENTRY_COUNT=1" in output
        assert "FLAGGED_COUNT=1" in output
        assert "GE-20260826-aaaaaa" in output
