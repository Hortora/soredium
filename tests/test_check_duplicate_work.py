"""Tests for scripts/check_duplicate_work.py — duplicate work detection."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import worklog

SCRIPT = str(Path(__file__).parent.parent / "scripts" / "check_duplicate_work.py")


def _run(issue_repo: str, issues: str, db_path: str) -> dict[str, str]:
    env = {"WORKLOG_DB": db_path, "PATH": "/opt/homebrew/bin:/usr/bin:/bin"}
    result = subprocess.run(
        [sys.executable, SCRIPT, issue_repo, f"issues={issues}"],
        capture_output=True, text=True, env=env,
    )
    output = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            output.setdefault(k.strip(), []).append(v.strip())
    flat = {}
    for k, vals in output.items():
        flat[k] = vals[0] if len(vals) == 1 else vals
    return flat


class TestDuplicateDetection:
    def test_no_active_work_returns_no(self, tmp_path):
        db = str(tmp_path / "worklog.db")
        conn = worklog.connect(db)
        conn.close()
        result = _run("org/engine", "42", db)
        assert result["DUPLICATE"] == "no"

    def test_active_work_returns_yes(self, tmp_path):
        db = str(tmp_path / "worklog.db")
        conn = worklog.connect(db)
        worklog.record_work_start(
            conn, "issue-42-first", "/repo/engine",
            issue_number=42, issue_repo="org/engine",
        )
        conn.close()
        result = _run("org/engine", "42", db)
        assert result["DUPLICATE"] == "yes"
        assert "issue-42-first" in result["ACTIVE_BRANCHES"]

    def test_ended_work_not_detected(self, tmp_path):
        db = str(tmp_path / "worklog.db")
        conn = worklog.connect(db)
        worklog.record_work_start(
            conn, "issue-42-old", "/repo/engine",
            issue_number=42, issue_repo="org/engine",
        )
        conn.execute("UPDATE work_items SET state='ended' WHERE branch='issue-42-old'")
        conn.commit()
        conn.close()
        result = _run("org/engine", "42", db)
        assert result["DUPLICATE"] == "no"

    def test_multiple_issues_checked(self, tmp_path):
        db = str(tmp_path / "worklog.db")
        conn = worklog.connect(db)
        worklog.record_work_start(
            conn, "issue-55-other", "/repo/engine",
            issue_number=55, issue_repo="org/engine",
        )
        conn.close()
        result = _run("org/engine", "42,55", db)
        assert result["DUPLICATE"] == "yes"
        assert "issue-55-other" in result["ACTIVE_BRANCHES"]

    def test_conflict_details_include_branch_and_location(self, tmp_path):
        db = str(tmp_path / "worklog.db")
        conn = worklog.connect(db)
        worklog.record_work_start(
            conn, "issue-42-slot", "/slot/engine",
            issue_number=42, issue_repo="org/engine",
            location="slot",
        )
        conn.close()
        result = _run("org/engine", "42", db)
        assert result["DUPLICATE"] == "yes"
        conflicts = result.get("CONFLICT", [])
        if isinstance(conflicts, str):
            conflicts = [conflicts]
        assert any("slot" in c for c in conflicts)
