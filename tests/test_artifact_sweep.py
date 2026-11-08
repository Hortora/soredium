"""Tests for work-end/artifact_sweep.py — workspace→project artifact gap detection."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit",
                    "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)
    return path


class TestSweepGapDetection:

    def test_detects_blog_entry_missing_from_project(self, tmp_path):
        from artifact_sweep import find_gaps

        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")

        (ws / "blog").mkdir()
        (ws / "blog" / "2026-11-01-entry.md").write_text("# Entry\n")

        (proj / "docs" / "blog").mkdir(parents=True)

        gaps = find_gaps(ws, proj)
        assert len(gaps) > 0
        assert any(g["source"].endswith("2026-11-01-entry.md") for g in gaps)

    def test_no_gap_when_entry_exists_in_project(self, tmp_path):
        from artifact_sweep import find_gaps

        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")

        (ws / "blog").mkdir()
        (ws / "blog" / "2026-11-01-entry.md").write_text("# Entry\n")

        (proj / "docs" / "blog").mkdir(parents=True)
        (proj / "docs" / "blog" / "2026-11-01-entry.md").write_text("# Entry\n")

        gaps = find_gaps(ws, proj)
        blog_gaps = [g for g in gaps if "2026-11-01-entry.md" in g["source"]]
        assert len(blog_gaps) == 0

    def test_detects_spec_missing_from_project(self, tmp_path):
        from artifact_sweep import find_gaps

        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")

        (ws / "specs" / "issue-42").mkdir(parents=True)
        (ws / "specs" / "issue-42" / "design.md").write_text("# Design\n")

        gaps = find_gaps(ws, proj)
        assert any("design.md" in g["source"] for g in gaps)

    def test_detects_adr_missing_from_project(self, tmp_path):
        from artifact_sweep import find_gaps

        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")

        (ws / "docs" / "adr").mkdir(parents=True)
        (ws / "docs" / "adr" / "ADR-0001.md").write_text("# ADR\n")

        (proj / "docs" / "adr").mkdir(parents=True)

        gaps = find_gaps(ws, proj)
        assert any("ADR-0001.md" in g["source"] for g in gaps)

    def test_multiple_categories(self, tmp_path):
        from artifact_sweep import find_gaps

        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")

        (ws / "blog").mkdir()
        (ws / "blog" / "entry1.md").write_text("# E1\n")
        (ws / "specs").mkdir()
        (ws / "specs" / "spec1.md").write_text("# S1\n")

        gaps = find_gaps(ws, proj)
        categories = {g["category"] for g in gaps}
        assert "blog" in categories
        assert "specs" in categories


class TestSweepPromote:

    def test_promote_copies_to_project(self, tmp_path):
        from artifact_sweep import find_gaps, promote_gaps

        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")

        (ws / "blog").mkdir()
        (ws / "blog" / "2026-11-01-entry.md").write_text("# Entry\n")

        gaps = find_gaps(ws, proj)
        result = promote_gaps(gaps, proj)

        assert result["promoted"] > 0
        assert (proj / "docs" / "blog" / "2026-11-01-entry.md").exists()

    def test_promote_commits_to_project(self, tmp_path):
        from artifact_sweep import find_gaps, promote_gaps

        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")

        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("# E\n")

        gaps = find_gaps(ws, proj)
        promote_gaps(gaps, proj)

        status = subprocess.run(
            ["git", "-C", str(proj), "status", "--porcelain"],
            capture_output=True, text=True).stdout.strip()
        assert status == "", "promoted artifacts must be committed"

    def test_promote_empty_gaps_is_noop(self, tmp_path):
        proj = _init_repo(tmp_path / "project")
        from artifact_sweep import promote_gaps
        result = promote_gaps([], proj)
        assert result["promoted"] == 0
