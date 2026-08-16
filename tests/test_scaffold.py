#!/usr/bin/env python3
"""
Tests for work-start/scaffold.py

Covers: happy path field writing, idempotency, missing workspace,
missing required params, defaults, unified .plan format correctness.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

SCRIPT = Path(__file__).parent.parent / "work-start" / "scaffold.py"


def run(workspace: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(workspace)] + list(extra_args),
        capture_output=True, text=True,
    )


def parse(result: subprocess.CompletedProcess) -> dict:
    return dict(line.split("=", 1) for line in result.stdout.strip().splitlines() if "=" in line)


def required_args(**overrides) -> list[str]:
    defaults = {
        "branch": "issue-42-auth-flow",
        "project-sha": "abc1234",
        "date": "2026-06-08",
    }
    defaults.update(overrides)
    return [f"{k}={v}" for k, v in defaults.items()]


def _read_plan(ws: Path) -> str:
    return (ws / ".plan").read_text()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:

    def test_creates_plan_at_root(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args())
        assert (ws / ".plan").exists()
        assert not (ws / "design" / ".plan").exists()

    def test_does_not_create_meta_file(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args())
        assert not (ws / ".meta").exists()
        assert not (ws / "design" / ".meta").exists()

    def test_creates_journal_md(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args())
        assert (ws / "JOURNAL.md").exists()

    def test_journal_contains_branch_heading(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args(branch="issue-99-payments"))
        content = (ws / "JOURNAL.md").read_text()
        assert "issue-99-payments" in content

    def test_plan_contains_state_section(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args(branch="issue-42-auth", **{"project-sha": "deadbeef"}))
        plan = _read_plan(ws)
        assert "## State" in plan
        assert "branch: issue-42-auth" in plan
        assert "project-sha: deadbeef" in plan
        assert "state: scaffolded" in plan

    def test_plan_optional_fields_written(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args(
            issue="42",
            covers="42,43",
            **{"flyway-next-v": "17", "design-repo": "workspace"}
        ))
        plan = _read_plan(ws)
        assert "covers: 42,43" in plan
        assert "flyway-next-v: 17" in plan
        assert "design-repo: workspace" in plan

    def test_output_contains_plan_and_journal_paths(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run(ws, *required_args())
        out = parse(result)
        assert "PLAN_PATH" in out
        assert "JOURNAL_PATH" in out
        assert out["CREATED"] == "yes"

    def test_creates_files_at_workspace_root(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args())
        assert (ws / ".plan").exists()
        assert (ws / "JOURNAL.md").exists()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:

    def test_second_run_does_not_overwrite(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args(branch="issue-42-auth"))
        plan = ws / ".plan"
        plan.write_text("# modified\n")
        run(ws, *required_args(branch="issue-42-auth"))
        assert "modified" in plan.read_text()

    def test_second_run_returns_created_no(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args())
        result = run(ws, *required_args())
        out = parse(result)
        assert out["CREATED"] == "no"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestDefaults:

    def test_flyway_defaults_to_unknown(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args())
        plan = _read_plan(ws)
        assert "flyway-next-v: unknown" in plan

    def test_design_repo_defaults_to_project(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args())
        plan = _read_plan(ws)
        assert "design-repo: project" in plan

    def test_covers_defaults_to_issue_when_given(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run(ws, *required_args(issue="55"))
        plan = _read_plan(ws)
        assert "covers: 55" in plan


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrorCases:

    def test_exits_1_when_workspace_missing(self, tmp_path):
        result = run(tmp_path / "nonexistent", *required_args())
        assert result.returncode == 1

    def test_exits_1_when_branch_missing(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run(ws, "project-sha=abc")
        assert result.returncode == 1

    def test_exits_1_when_project_sha_missing(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run(ws, "branch=issue-42")
        assert result.returncode == 1

    def test_exits_1_when_no_args(self, tmp_path):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# Worklog issue-activate integration
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


class TestScaffoldIssueActivate:

    def _run_with_db(self, workspace, db_path, *extra_args):
        env = {**os.environ, "WORKLOG_DB": db_path}
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(workspace)] + list(extra_args),
            capture_output=True, text=True, env=env,
        )

    def _get_events(self, db_path, event_type):
        sys.path.insert(0, str(SCRIPTS_DIR))
        import worklog
        conn = worklog.connect(db_path)
        events = worklog.event_log(conn, event_type=event_type)
        conn.close()
        return events

    def test_emits_issue_activate_after_work_start(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        db_path = str(tmp_path / "test-worklog.db")
        result = self._run_with_db(ws, db_path, *required_args(
            issue="42", **{"issue-repo": "Org/repo", "covers": "42"}))
        assert result.returncode == 0
        events = self._get_events(db_path, "issue-activate")
        assert len(events) == 1
        meta = json.loads(events[0]["metadata"])
        assert meta["issue_number"] == 42
        assert meta["issue_repo"] == "Org/repo"

    def test_skips_issue_activate_when_no_issue(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        db_path = str(tmp_path / "test-worklog.db")
        self._run_with_db(ws, db_path, *required_args())
        events = self._get_events(db_path, "issue-activate")
        assert len(events) == 0

    def test_scaffold_succeeds_without_worklog_env(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run(ws, *required_args(issue="42", **{"issue-repo": "Org/repo"}))
        assert result.returncode == 0
        out = parse(result)
        assert out["CREATED"] == "yes"
