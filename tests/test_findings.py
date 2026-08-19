"""Tests for unified findings persistence library."""
import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from findings import read_findings, append_finding, compact_findings


class TestReadFindings:
    def test_empty_file(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        path.write_text("")
        assert read_findings(path) == []

    def test_file_not_found(self):
        assert read_findings(Path("/nonexistent/findings.jsonl")) == []

    def test_single_finding(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        finding = {
            "category": "hygiene", "check": "stale_branch",
            "location": "branch:issue-100", "detail": "stale",
            "status": "open", "timestamp": "2026-08-19T10:00:00Z",
        }
        path.write_text(json.dumps(finding) + "\n")
        result = read_findings(path)
        assert len(result) == 1
        assert result[0]["status"] == "open"

    def test_dedup_by_check_location_branch(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        f1 = {
            "category": "audit", "check": "missing-req",
            "location": "spec:req-3", "branch": "issue-123",
            "detail": "v1", "severity": "warning",
            "status": "open", "timestamp": "2026-08-19T10:00:00Z",
        }
        f2 = {
            **f1, "detail": "v2", "status": "resolved",
            "resolution": "fixed in abc1234",
            "timestamp": "2026-08-19T11:00:00Z",
        }
        path.write_text(json.dumps(f1) + "\n" + json.dumps(f2) + "\n")
        result = read_findings(path)
        assert len(result) == 1
        assert result[0]["status"] == "resolved"

    def test_highest_severity_wins(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        f1 = {
            "category": "review", "check": "unsafe-code",
            "location": "src/x.py:42", "branch": "issue-123",
            "detail": "bad", "severity": "critical",
            "status": "open", "timestamp": "2026-08-19T10:00:00Z",
        }
        f2 = {**f1, "severity": "warning", "timestamp": "2026-08-19T11:00:00Z"}
        path.write_text(json.dumps(f1) + "\n" + json.dumps(f2) + "\n")
        result = read_findings(path)
        assert result[0]["severity"] == "critical"

    def test_default_severity_is_warning(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        finding = {
            "category": "hygiene", "check": "stale_branch",
            "location": "branch:issue-100", "detail": "stale",
            "status": "open", "timestamp": "2026-08-19T10:00:00Z",
        }
        path.write_text(json.dumps(finding) + "\n")
        result = read_findings(path)
        assert result[0]["severity"] == "warning"

    def test_fallback_dedup_when_no_location(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        f1 = {
            "category": "hygiene", "check": "stale_branch",
            "detail": "issue-100 stale", "status": "open",
            "timestamp": "2026-08-19T10:00:00Z",
        }
        f2 = {
            **f1, "status": "dismissed", "resolution": "cleaned up",
            "timestamp": "2026-08-19T11:00:00Z",
        }
        path.write_text(json.dumps(f1) + "\n" + json.dumps(f2) + "\n")
        result = read_findings(path)
        assert len(result) == 1
        assert result[0]["status"] == "dismissed"

    def test_latest_timestamp_wins_for_status(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        f1 = {
            "category": "audit", "check": "missing-req",
            "location": "spec:req-3", "branch": "issue-123",
            "detail": "not impl", "severity": "warning",
            "status": "resolved", "resolution": "fixed",
            "timestamp": "2026-08-19T10:00:00Z",
        }
        f2 = {
            **f1, "status": "open", "resolution": None,
            "timestamp": "2026-08-19T12:00:00Z",
        }
        path.write_text(json.dumps(f1) + "\n" + json.dumps(f2) + "\n")
        result = read_findings(path)
        assert result[0]["status"] == "open"

    def test_source_from_highest_severity_entry(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        f1 = {
            "category": "audit", "check": "unsafe-code",
            "location": "src/x.py:42", "branch": "issue-123",
            "detail": "bad", "severity": "critical",
            "source": "branch-audit",
            "status": "open", "timestamp": "2026-08-19T10:00:00Z",
        }
        f2 = {
            **f1, "severity": "warning", "source": "code-review",
            "timestamp": "2026-08-19T11:00:00Z",
        }
        path.write_text(json.dumps(f1) + "\n" + json.dumps(f2) + "\n")
        result = read_findings(path)
        assert result[0]["source"] == "branch-audit"

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        valid = {
            "category": "hygiene", "check": "stale_branch",
            "location": "branch:issue-100", "detail": "stale",
            "status": "open", "timestamp": "2026-08-19T10:00:00Z",
        }
        path.write_text("not json\n" + json.dumps(valid) + "\n\n")
        result = read_findings(path)
        assert len(result) == 1

    def test_different_branches_not_deduped(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        f1 = {
            "category": "audit", "check": "missing-req",
            "location": "spec:req-3", "branch": "issue-100",
            "detail": "not impl", "severity": "warning",
            "status": "open", "timestamp": "2026-08-19T10:00:00Z",
        }
        f2 = {**f1, "branch": "issue-200"}
        path.write_text(json.dumps(f1) + "\n" + json.dumps(f2) + "\n")
        result = read_findings(path)
        assert len(result) == 2


class TestAppendFinding:
    def test_creates_file_and_parent_dirs(self, tmp_path):
        path = tmp_path / ".audit" / "findings.jsonl"
        finding = {
            "category": "audit", "check": "test",
            "detail": "x", "status": "open",
            "timestamp": "2026-08-19T10:00:00Z",
        }
        append_finding(path, finding)
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["check"] == "test"

    def test_appends_to_existing(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        f1 = {"category": "audit", "check": "a", "detail": "x",
              "status": "open", "timestamp": "2026-08-19T10:00:00Z"}
        f2 = {"category": "audit", "check": "b", "detail": "y",
              "status": "open", "timestamp": "2026-08-19T11:00:00Z"}
        append_finding(path, f1)
        append_finding(path, f2)
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2


class TestCompactFindings:
    def test_archives_old_resolved(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        archive = tmp_path / "findings-archive.jsonl"
        old = {
            "category": "audit", "check": "a", "detail": "x",
            "status": "resolved", "resolution": "fixed",
            "timestamp": "2026-07-01T10:00:00Z",
        }
        current = {
            "category": "audit", "check": "b", "detail": "y",
            "status": "open",
            "timestamp": "2026-08-19T10:00:00Z",
        }
        path.write_text(json.dumps(old) + "\n" + json.dumps(current) + "\n")
        archived = compact_findings(path, archive)
        assert archived == 1
        remaining = path.read_text().strip().split("\n")
        assert len(remaining) == 1
        assert json.loads(remaining[0])["check"] == "b"
        assert archive.exists()

    def test_no_file_returns_zero(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        archive = tmp_path / "findings-archive.jsonl"
        assert compact_findings(path, archive) == 0

    def test_keeps_recent_resolved(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        archive = tmp_path / "findings-archive.jsonl"
        recent = {
            "category": "audit", "check": "a", "detail": "x",
            "status": "resolved", "resolution": "fixed",
            "timestamp": "2026-08-19T10:00:00Z",
        }
        path.write_text(json.dumps(recent) + "\n")
        archived = compact_findings(path, archive)
        assert archived == 0
        assert path.read_text().strip() != ""

    def test_keeps_open_findings(self, tmp_path):
        path = tmp_path / "findings.jsonl"
        archive = tmp_path / "findings-archive.jsonl"
        old_open = {
            "category": "audit", "check": "a", "detail": "x",
            "status": "open",
            "timestamp": "2026-01-01T10:00:00Z",
        }
        path.write_text(json.dumps(old_open) + "\n")
        archived = compact_findings(path, archive)
        assert archived == 0
