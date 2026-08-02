"""Tests for scripts/audit_slot_artifacts.py false positive filters."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from audit_slot_artifacts import (
    filter_proj_symlinks,
    filter_inherited,
    filter_already_recovered,
)


class TestFilterProjSymlinks:
    def test_proj_paths_removed(self):
        findings = [
            {"file": "proj/docs/specs/design.md", "type": "docs"},
            {"file": "specs/real-spec.md", "type": "specs"},
            {"file": "proj/docs/plans/plan.md", "type": "docs"},
        ]
        result = filter_proj_symlinks(findings)
        assert len(result) == 1
        assert result[0]["file"] == "specs/real-spec.md"

    def test_no_proj_paths_unchanged(self):
        findings = [
            {"file": "specs/design.md", "type": "specs"},
            {"file": "blog/entry.md", "type": "blog"},
        ]
        result = filter_proj_symlinks(findings)
        assert len(result) == 2


class TestFilterInherited:
    def test_files_in_3_plus_slots_removed(self):
        findings = [
            {"file": "engine/blog/inherited.md", "slot": "1", "type": "blog"},
            {"file": "engine/blog/inherited.md", "slot": "2", "type": "blog"},
            {"file": "engine/blog/inherited.md", "slot": "3", "type": "blog"},
            {"file": "specs/unique-spec.md", "slot": "1", "type": "specs"},
        ]
        result = filter_inherited(findings, threshold=3)
        assert len(result) == 1
        assert result[0]["file"] == "specs/unique-spec.md"

    def test_files_in_2_slots_kept(self):
        findings = [
            {"file": "blog/entry.md", "slot": "1", "type": "blog"},
            {"file": "blog/entry.md", "slot": "2", "type": "blog"},
        ]
        result = filter_inherited(findings, threshold=3)
        assert len(result) == 2

    def test_same_filename_different_paths_not_collapsed(self):
        findings = [
            {"file": "engine/blog/entry.md", "slot": "1", "type": "blog"},
            {"file": "platform/blog/entry.md", "slot": "2", "type": "blog"},
            {"file": "blocks/blog/entry.md", "slot": "3", "type": "blog"},
        ]
        result = filter_inherited(findings, threshold=3)
        assert len(result) == 3


class TestFilterAlreadyRecovered:
    def test_file_at_destination_removed(self, tmp_path):
        ws_main = tmp_path / "workspace"
        (ws_main / "blog").mkdir(parents=True)
        (ws_main / "blog" / "recovered.md").write_text("content")

        findings = [
            {"file": "blog/recovered.md", "type": "blog"},
            {"file": "blog/still-lost.md", "type": "blog"},
        ]
        result = filter_already_recovered(findings, ws_main)
        assert len(result) == 1
        assert result[0]["file"] == "blog/still-lost.md"

    def test_no_workspace_main_returns_all(self):
        findings = [{"file": "blog/entry.md", "type": "blog"}]
        result = filter_already_recovered(findings, Path("/nonexistent"))
        assert len(result) == 1
