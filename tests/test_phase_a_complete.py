"""Tests for work-end/phase_a_complete.py"""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "work-end" / "phase_a_complete.py"


def run(slot_root: str, **kwargs: str) -> subprocess.CompletedProcess:
    args = [sys.executable, str(SCRIPT), slot_root]
    args += [f"{k}={v}" for k, v in kwargs.items()]
    return subprocess.run(args, capture_output=True, text=True)


def parse(result: subprocess.CompletedProcess) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


class TestPhaseAComplete:
    def test_writes_marker_file(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        result = run(
            str(slot),
            branch="issue-42-feat",
            repos="engine,ledger",
        )
        assert result.returncode == 0
        out = parse(result)
        assert "MARKER" in out
        marker = slot / ".phase-a-complete"
        assert marker.exists()
        content = marker.read_text()
        assert "branch=issue-42-feat" in content
        assert "repos=engine,ledger" in content
        assert "timestamp=" in content

    def test_missing_branch(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        result = run(str(slot), repos="engine")
        assert result.returncode == 1
        assert "missing_branch" in result.stdout

    def test_missing_repos(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        result = run(str(slot), branch="issue-42")
        assert result.returncode == 1
        assert "missing_repos" in result.stdout

    def test_worklog_skipped_without_family_root(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        result = run(str(slot), branch="issue-42", repos="engine")
        assert result.returncode == 0
        out = parse(result)
        assert out.get("WORKLOG") == "skipped"


SCRIPTS_DIR = str(Path(__file__).parent.parent / "scripts")


class TestWorklogRecording:
    @pytest.fixture(autouse=True)
    def _load_worklog(self):
        """Ensure we import worklog from scripts/, not ~/.claude/lib/."""
        if SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, SCRIPTS_DIR)
        if "worklog" in sys.modules:
            del sys.modules["worklog"]

    def test_records_phase_a_in_worklog(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        family = tmp_path / "family"
        family.mkdir()

        db_path = tmp_path / "test.db"

        import worklog

        conn = worklog.connect(str(db_path))
        worklog.record_slot_create(
            conn, 1, str(family),
            repos=[str(family / "engine")],
            branch="issue-42", issue_number=42,
            issue_repo="owner/repo",
        )

        worklog.record_slot_phase_a(conn, 1, str(family))

        events = worklog.event_log(conn, event_type="slot-phase-a")
        assert len(events) == 1

        slots = worklog.slot_status(conn, str(family))
        assert len(slots) == 1
        assert slots[0]["state"] == "ready"
        conn.close()

    def test_enriched_archive_metadata(self, tmp_path):
        """record_slot_archive stores promoted/published/path metadata."""
        db_path = tmp_path / "test.db"
        family = tmp_path / "family"
        family.mkdir()

        import worklog

        conn = worklog.connect(str(db_path))
        worklog.record_slot_create(
            conn, 1, str(family),
            repos=[str(family / "engine")],
            branch="issue-42", issue_number=42,
            issue_repo="owner/repo",
        )

        worklog.record_slot_archive(
            conn, 1, str(family),
            promoted=["workspace:2", "project:1"],
            published=["blog:1"],
            publish_dest="/Users/dev/blog",
            archived_from=str(family / "slots/1"),
            archived_to=str(family / "slots/attic/1"),
        )

        events = worklog.event_log(conn, event_type="slot-archive")
        assert len(events) == 1
        import json
        meta = json.loads(events[0]["metadata"])
        assert meta["promoted"] == ["workspace:2", "project:1"]
        assert meta["published"] == ["blog:1"]
        assert meta["archived_from"] == str(family / "slots/1")
        assert meta["archived_to"] == str(family / "slots/attic/1")
        conn.close()