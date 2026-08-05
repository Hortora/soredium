"""Tests for worklog_mcp_server — 4 MCP tools over worklog.db."""

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import worklog

# Mock the mcp package so tests run without it installed
_mock_mcp = types.ModuleType("mcp")
_mock_server = types.ModuleType("mcp.server")
_mock_fastmcp_mod = types.ModuleType("mcp.server.fastmcp")


class _MockFastMCP:
    def __init__(self, name):
        self.name = name

    def tool(self):
        def decorator(fn):
            return fn
        return decorator

    def run(self):
        pass


_mock_fastmcp_mod.FastMCP = _MockFastMCP
_mock_mcp.server = _mock_server
_mock_server.fastmcp = _mock_fastmcp_mod
sys.modules.setdefault("mcp", _mock_mcp)
sys.modules.setdefault("mcp.server", _mock_server)
sys.modules.setdefault("mcp.server.fastmcp", _mock_fastmcp_mod)

import worklog_mcp_server


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Create a temp worklog database and point the server at it."""
    db_path = str(tmp_path / "test-worklog.db")
    monkeypatch.setenv("WORKLOG_DB", db_path)
    conn = worklog.connect(db_path)
    worklog.ensure_repo(conn, "/repo/project", github_repo="Org/repo")
    yield conn
    conn.close()


def _start(db):
    worklog.record_work_start(
        db, "issue-42-fix", "/repo/project",
        issue_number=42, issue_repo="Org/repo",
    )


class TestWorklogActive:
    def test_returns_empty_on_fresh_db(self, db):
        result = worklog_mcp_server.worklog_active()
        assert result == []

    def test_returns_started_items(self, db):
        _start(db)
        result = worklog_mcp_server.worklog_active()
        assert len(result) == 1
        assert result[0]["branch"] == "issue-42-fix"
        assert result[0]["state"] == "active"

    def test_excludes_ended_items(self, db):
        _start(db)
        worklog.record_work_end(db, "issue-42-fix", "/repo/project")
        result = worklog_mcp_server.worklog_active()
        assert result == []

    def test_returns_error_dict_on_db_failure(self, monkeypatch):
        monkeypatch.setenv("WORKLOG_DB", "/nonexistent/path/db.sqlite")
        with patch("worklog.connect", side_effect=Exception("boom")):
            result = worklog_mcp_server.worklog_active()
        assert isinstance(result, dict)
        assert "error" in result


class TestWorklogEvents:
    def test_returns_all_when_unfiltered(self, db):
        _start(db)
        result = worklog_mcp_server.worklog_events()
        assert len(result) >= 1
        assert result[0]["event_type"] == "work-start"

    def test_filters_by_type(self, db):
        _start(db)
        worklog.record_work_end(db, "issue-42-fix", "/repo/project")
        result = worklog_mcp_server.worklog_events(event_type="work-end")
        assert all(e["event_type"] == "work-end" for e in result)

    def test_filters_by_since(self, db):
        _start(db)
        result = worklog_mcp_server.worklog_events(since="2099-01-01T00:00:00")
        assert result == []

    def test_respects_limit(self, db):
        _start(db)
        worklog.record_work_end(db, "issue-42-fix", "/repo/project")
        result = worklog_mcp_server.worklog_events(limit=1)
        assert len(result) == 1

    def test_normalizes_repo_path(self, db):
        _start(db)
        result = worklog_mcp_server.worklog_events(repo_path="/repo/project")
        assert len(result) >= 1

    def test_metadata_is_parsed_dict(self, db):
        _start(db)
        worklog.record_issue_activate(
            db, "issue-42-fix", "/repo/project", 42, "Org/repo",
        )
        result = worklog_mcp_server.worklog_events(event_type="issue-activate")
        assert len(result) >= 1
        meta = result[0]["metadata"]
        assert isinstance(meta, dict)
        assert meta["issue_number"] == 42


class TestWorklogTimeline:
    def test_returns_branch_events(self, db):
        _start(db)
        result = worklog_mcp_server.worklog_timeline(
            branch="issue-42-fix", repo_path="/repo/project",
        )
        assert len(result) >= 1
        assert result[0]["event_type"] == "work-start"

    def test_empty_for_unknown_branch(self, db):
        result = worklog_mcp_server.worklog_timeline(
            branch="nonexistent", repo_path="/repo/project",
        )
        assert result == []

    def test_metadata_is_parsed_dict(self, db):
        _start(db)
        worklog.record_issue_activate(
            db, "issue-42-fix", "/repo/project", 42, "Org/repo",
        )
        result = worklog_mcp_server.worklog_timeline(
            branch="issue-42-fix", repo_path="/repo/project",
        )
        activate_events = [e for e in result if e["event_type"] == "issue-activate"]
        assert len(activate_events) >= 1
        assert isinstance(activate_events[0]["metadata"], dict)


class TestWorklogSlots:
    def test_returns_all(self, db):
        worklog.record_slot_create(
            db, slot_number=1, family_root="/family",
            repos=["/family/repo"], branch="issue-50-epic",
            issue_number=50, issue_repo="Org/repo",
        )
        result = worklog_mcp_server.worklog_slots()
        assert len(result) == 1
        assert result[0]["slot_number"] == 1

    def test_filters_by_family_root(self, db):
        worklog.record_slot_create(
            db, slot_number=1, family_root="/family-a",
            repos=["/family-a/repo"], branch="issue-50-a",
            issue_number=50, issue_repo="Org/repo",
        )
        worklog.record_slot_create(
            db, slot_number=2, family_root="/family-b",
            repos=["/family-b/repo"], branch="issue-51-b",
            issue_number=51, issue_repo="Org/repo",
        )
        result = worklog_mcp_server.worklog_slots(family_root="/family-a")
        assert len(result) == 1
        assert result[0]["family_root"] == str(Path("/family-a").resolve())
