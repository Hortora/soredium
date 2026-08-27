"""Tests for work-end/verify_slot_close.py — post-close audit."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_work_end = Path(__file__).resolve().parent.parent / "work-end"
sys.path.insert(0, str(_work_end))

from verify_slot_close import (
    check_no_open_findings,
    check_no_stale_scaffold,
    check_landed_marker,
    check_landed_completeness,
    check_on_main,
    check_slot_marker,
)


class TestNoOpenFindings:
    def test_no_findings_file(self, tmp_path):
        result = check_no_open_findings(str(tmp_path))
        assert result["status"] == "pass"

    def test_all_resolved(self, tmp_path):
        audit = tmp_path / ".audit"
        audit.mkdir()
        findings = [
            {"status": "resolved", "detail": "fixed", "check": "t", "branch": "t"},
            {"status": "dismissed", "detail": "ok", "check": "t2", "branch": "t"},
        ]
        (audit / "findings.jsonl").write_text(
            "\n".join(json.dumps(f) for f in findings) + "\n"
        )
        result = check_no_open_findings(str(tmp_path))
        assert result["status"] == "pass"

    def test_open_finding_fails(self, tmp_path):
        audit = tmp_path / ".audit"
        audit.mkdir()
        finding = {"status": "open", "detail": "bug", "check": "t", "branch": "t"}
        (audit / "findings.jsonl").write_text(json.dumps(finding) + "\n")
        result = check_no_open_findings(str(tmp_path))
        assert result["status"] == "fail"
        assert "1 open" in result["detail"]


class TestNoStaleScaffold:
    def test_clean_workspace(self, tmp_path):
        result = check_no_stale_scaffold(str(tmp_path))
        assert result["status"] == "pass"

    def test_stale_execute_progress(self, tmp_path):
        (tmp_path / ".execute-progress").write_text("test")
        result = check_no_stale_scaffold(str(tmp_path))
        assert result["status"] == "warn"
        assert ".execute-progress" in result["detail"]


class TestLandedMarker:
    def test_missing_marker(self, tmp_path):
        result = check_landed_marker(str(tmp_path))
        assert result["status"] == "fail"

    def test_marker_is_directory(self, tmp_path):
        (tmp_path / ".landed").mkdir()
        result = check_landed_marker(str(tmp_path))
        assert result["status"] == "fail"
        assert "directory" in result["detail"]

    def test_marker_without_shas(self, tmp_path):
        (tmp_path / ".landed").write_text("branch=test\n")
        result = check_landed_marker(str(tmp_path))
        assert result["status"] == "fail"

    def test_valid_marker(self, tmp_path):
        (tmp_path / ".landed").write_text("landed_shas=repo:abc123\nbranch=test\n")
        result = check_landed_marker(str(tmp_path))
        assert result["status"] == "pass"


class TestSlotMarker:
    def test_missing_marker(self, tmp_path):
        result = check_slot_marker(str(tmp_path), ".phase-a-complete")
        assert result["status"] == "fail"
        assert "missing" in result["detail"]

    def test_marker_is_dir(self, tmp_path):
        (tmp_path / ".phase-a-complete").mkdir()
        result = check_slot_marker(str(tmp_path), ".phase-a-complete")
        assert result["status"] == "fail"
        assert "directory" in result["detail"]

    def test_valid_marker(self, tmp_path):
        (tmp_path / ".phase-a-complete").write_text("")
        result = check_slot_marker(str(tmp_path), ".phase-a-complete")
        assert result["status"] == "pass"


class TestLandedCompleteness:
    def test_all_repos_landed(self, tmp_path):
        (tmp_path / ".slot").write_text("## Repos\n- pages (primary)\n- blocks-ui\n- examples\n")
        (tmp_path / ".landed").write_text("landed_shas=pages:abc,blocks-ui:def,examples:ghi\n")
        result = check_landed_completeness(str(tmp_path))
        assert result["status"] == "pass"
        assert "3/3" in result["detail"]

    def test_missing_repo_in_landed(self, tmp_path):
        (tmp_path / ".slot").write_text("## Repos\n- pages (primary)\n- blocks-ui\n- examples\n")
        (tmp_path / ".landed").write_text("landed_shas=examples:abc\n")
        result = check_landed_completeness(str(tmp_path))
        assert result["status"] == "fail"
        assert "blocks-ui" in result["detail"]
        assert "pages" in result["detail"]

    def test_no_landed_file(self, tmp_path):
        (tmp_path / ".slot").write_text("## Repos\n- pages\n- blocks-ui\n")
        result = check_landed_completeness(str(tmp_path))
        assert result["status"] == "fail"


class TestSlotPathFix:
    """Regression: SLOT_PATH must be a directory, not the .slot file."""

    def test_ctx_slot_path_is_directory(self):
        """ctx.py should output the slot directory, not the .slot file."""
        ctx_path = Path(__file__).resolve().parent.parent / "project" / "ctx.py"
        content = ctx_path.read_text()
        assert 'str(topo.slot_dir / ".slot")' not in content, \
            "SLOT_PATH should be slot_dir (directory), not slot_dir/.slot (file)"
        assert 'str(topo.slot_dir)' in content
