"""Tests for close-time audit checks — verification/close_checks.py."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from verification.close_checks import (
    check_no_open_findings,
    check_no_stale_scaffold,
    check_landed_marker,
    check_landed_completeness,
    check_on_main,
    check_slot_marker,
)


class TestNoOpenFindings:
    def test_no_findings_file(self, tmp_path):
        findings = check_no_open_findings(tmp_path)
        assert findings == []

    def test_all_resolved(self, tmp_path):
        audit = tmp_path / ".audit"
        audit.mkdir()
        entries = [
            {"status": "resolved", "detail": "fixed", "check": "t", "branch": "t"},
            {"status": "dismissed", "detail": "ok", "check": "t2", "branch": "t"},
        ]
        (audit / "findings.jsonl").write_text(
            "\n".join(json.dumps(f) for f in entries) + "\n"
        )
        findings = check_no_open_findings(tmp_path)
        assert findings == []

    def test_open_finding_fails(self, tmp_path):
        audit = tmp_path / ".audit"
        audit.mkdir()
        entry = {"status": "open", "detail": "bug", "check": "t", "branch": "t"}
        (audit / "findings.jsonl").write_text(json.dumps(entry) + "\n")
        findings = check_no_open_findings(tmp_path)
        assert len(findings) == 1
        assert "1 open" in findings[0].message


class TestNoStaleScaffold:
    def test_clean_workspace(self, tmp_path):
        findings = check_no_stale_scaffold(tmp_path)
        assert findings == []

    def test_stale_execute_progress(self, tmp_path):
        (tmp_path / ".execute-progress").write_text("test")
        findings = check_no_stale_scaffold(tmp_path)
        assert len(findings) == 1
        assert ".execute-progress" in findings[0].message


class TestLandedMarker:
    def test_missing_marker(self, tmp_path):
        findings = check_landed_marker(tmp_path)
        assert len(findings) == 1

    def test_marker_is_directory(self, tmp_path):
        (tmp_path / ".landed").mkdir()
        findings = check_landed_marker(tmp_path)
        assert len(findings) == 1
        assert "directory" in findings[0].message

    def test_marker_without_shas(self, tmp_path):
        (tmp_path / ".landed").write_text("branch=test\n")
        findings = check_landed_marker(tmp_path)
        assert len(findings) == 1

    def test_valid_marker(self, tmp_path):
        (tmp_path / ".landed").write_text("landed_shas=repo:abc123\nbranch=test\n")
        findings = check_landed_marker(tmp_path)
        assert findings == []


class TestSlotMarker:
    def test_missing_marker(self, tmp_path):
        findings = check_slot_marker(tmp_path, ".phase-a-complete")
        assert len(findings) == 1
        assert "missing" in findings[0].message

    def test_marker_is_dir(self, tmp_path):
        (tmp_path / ".phase-a-complete").mkdir()
        findings = check_slot_marker(tmp_path, ".phase-a-complete")
        assert len(findings) == 1
        assert "directory" in findings[0].message

    def test_valid_marker(self, tmp_path):
        (tmp_path / ".phase-a-complete").write_text("")
        findings = check_slot_marker(tmp_path, ".phase-a-complete")
        assert findings == []


class TestLandedCompleteness:
    def test_all_repos_landed(self, tmp_path):
        (tmp_path / ".slot").write_text("## Repos\n- pages (primary)\n- blocks-ui\n- examples\n")
        (tmp_path / ".landed").write_text("landed_shas=pages:abc,blocks-ui:def,examples:ghi\n")
        findings = check_landed_completeness(tmp_path)
        assert findings == []

    def test_missing_repo_in_landed(self, tmp_path):
        (tmp_path / ".slot").write_text("## Repos\n- pages (primary)\n- blocks-ui\n- examples\n")
        (tmp_path / ".landed").write_text("landed_shas=examples:abc\n")
        findings = check_landed_completeness(tmp_path)
        assert len(findings) == 1
        assert "blocks-ui" in findings[0].message
        assert "pages" in findings[0].message

    def test_no_landed_file(self, tmp_path):
        (tmp_path / ".slot").write_text("## Repos\n- pages\n- blocks-ui\n")
        findings = check_landed_completeness(tmp_path)
        assert len(findings) == 1


class TestSlotPathFix:
    """Regression: SLOT_PATH must be a directory, not the .slot file."""

    def test_ctx_slot_path_is_directory(self):
        ctx_path = Path(__file__).resolve().parent.parent / "project" / "ctx.py"
        content = ctx_path.read_text()
        assert 'str(topo.slot_dir / ".slot")' not in content, \
            "SLOT_PATH should be slot_dir (directory), not slot_dir/.slot (file)"
        assert 'str(topo.slot_dir)' in content
