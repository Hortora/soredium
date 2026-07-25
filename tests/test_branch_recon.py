"""Tests for work-end/branch_recon.py"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

script_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(script_dir))

from branch_recon import (
    gather_commits,
    gather_diff_stats,
    parse_journal,
    check_arc42,
    compute_section_drift,
)


def _init_git(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)


class TestParseJournal:
    def test_empty_journal(self, tmp_path):
        (tmp_path / "design").mkdir()
        (tmp_path / "design" / "JOURNAL.md").write_text("# Journal\n\n")
        result = parse_journal(str(tmp_path))
        assert result["empty_journal"] is True
        assert result["journal_entry_count"] == 0

    def test_counts_entries(self, tmp_path):
        (tmp_path / "design").mkdir()
        (tmp_path / "design" / "JOURNAL.md").write_text(
            "# Journal\n\n"
            "### 2026-07-20 · Added auth · §S5\n\nDetails.\n\n"
            "### 2026-07-21 · Fixed bug\n\nMore details.\n\n"
            "### 2026-07-22 · Refactored · §S3\n\nDone.\n"
        )
        result = parse_journal(str(tmp_path))
        assert result["journal_entry_count"] == 3
        assert result["anchored_entries"] == 2
        assert result["unanchored_entries"] == 1
        assert result["empty_journal"] is False

    def test_unanchored_entries_listed(self, tmp_path):
        (tmp_path / "design").mkdir()
        (tmp_path / "design" / "JOURNAL.md").write_text(
            "### Entry without anchor\n\nText.\n"
        )
        result = parse_journal(str(tmp_path))
        assert result["entries_without_anchors"] == ["### Entry without anchor"]

    def test_missing_journal(self, tmp_path):
        result = parse_journal(str(tmp_path))
        assert result["empty_journal"] is True
        assert result["journal_entry_count"] == 0


class TestCheckArc42:
    def test_exists(self, tmp_path):
        (tmp_path / "ARC42STORIES.MD").write_text("# Design")
        assert check_arc42(str(tmp_path)) is True

    def test_missing(self, tmp_path):
        assert check_arc42(str(tmp_path)) is False

    def test_empty_design_repo(self):
        assert check_arc42("") is False


class TestComputeSectionDrift:
    def test_no_drift(self, tmp_path):
        import hashlib
        heading = "## S5 — Security"
        h = hashlib.sha256(heading.encode()).hexdigest()[:8]
        (tmp_path / "ARC42STORIES.MD").write_text(f"# Design\n\n{heading}\n\nContent.\n")
        meta_hashes = f"{h}:{heading}"
        drift, warnings = compute_section_drift(str(tmp_path), meta_hashes)
        assert drift == []
        assert warnings == []

    def test_detects_drift(self, tmp_path):
        (tmp_path / "ARC42STORIES.MD").write_text("# Design\n\n## S5 — Security\n\nContent.\n")
        meta_hashes = "deadbeef:## S5 — Security"
        drift, warnings = compute_section_drift(str(tmp_path), meta_hashes)
        assert len(drift) == 1
        assert drift[0]["section"] == "## S5 — Security"
        assert drift[0]["stored_hash"] == "deadbeef"

    def test_empty_design_repo(self):
        drift, warnings = compute_section_drift("", "abc:## S1")
        assert drift == []

    def test_empty_hashes(self, tmp_path):
        (tmp_path / "ARC42STORIES.MD").write_text("## S1\n")
        drift, warnings = compute_section_drift(str(tmp_path), "")
        assert drift == []


class TestParseJournalWarnings:
    def test_malformed_heading_produces_warning(self, tmp_path):
        (tmp_path / "design").mkdir()
        (tmp_path / "design" / "JOURNAL.md").write_text(
            "###No space after hashes\n\nContent.\n"
        )
        result = parse_journal(str(tmp_path))
        assert result["journal_entry_count"] == 0
        assert len(result["warnings"]) == 1
        assert "malformed" in result["warnings"][0]

    def test_h4_heading_not_flagged(self, tmp_path):
        (tmp_path / "design").mkdir()
        (tmp_path / "design" / "JOURNAL.md").write_text(
            "#### Subheading\n\nNot a journal entry.\n"
        )
        result = parse_journal(str(tmp_path))
        assert result["warnings"] == []


class TestComputeSectionDriftWarnings:
    def test_missing_script_produces_warning(self, tmp_path, monkeypatch):
        (tmp_path / "ARC42STORIES.MD").write_text("## S1\n")
        import branch_recon
        monkeypatch.setattr(branch_recon, "__file__", str(tmp_path / "fake" / "branch_recon.py"))
        drift, warnings = compute_section_drift(str(tmp_path), "abc:## S1")
        assert len(warnings) == 1
        assert "not found" in warnings[0]


class TestGatherCommits:
    def test_collects_commits(self, tmp_path):
        _init_git(tmp_path)
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "-b", "feature"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "feat: add thing"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "fix: broken thing"], capture_output=True)

        commits, count = gather_commits(str(tmp_path), "main", "feature")
        assert count == 2
        assert any("feat: add thing" in c["message"] for c in commits)
        assert any("fix: broken thing" in c["message"] for c in commits)

    def test_no_commits(self, tmp_path):
        _init_git(tmp_path)
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "-b", "empty-branch"], capture_output=True)

        commits, count = gather_commits(str(tmp_path), "main", "empty-branch")
        assert count == 0
        assert commits == []


class TestGatherDiffStats:
    def test_returns_stats(self, tmp_path):
        _init_git(tmp_path)
        sha_result = subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        sha = sha_result.stdout.strip()

        (tmp_path / "file.txt").write_text("content")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "add file"], capture_output=True)

        stats = gather_diff_stats(str(tmp_path), sha)
        assert "1 file changed" in stats


class TestIntegration:
    """Run the script as a subprocess and verify JSON output."""

    SCRIPT = Path(__file__).parent.parent / "work-end" / "branch_recon.py"

    def test_produces_valid_json(self, tmp_path):
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)
        (workspace / "design").mkdir()
        (workspace / "design" / "JOURNAL.md").write_text("# Journal\n\n### Entry · §S1\n\n")

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-42-feat"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat: thing"], capture_output=True)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project),
             "branch=issue-42-feat", "base_branch=main",
             "project_sha=HEAD~1"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "commits" in data
        assert "journal_validation" in data
        assert data["journal_entry_count"] == 1
        assert data["journal_validation"]["anchored_entries"] == 1

    def test_missing_branch_arg(self):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), "/tmp", "/tmp"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_warnings_in_output(self, tmp_path):
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)
        (workspace / "design").mkdir()
        (workspace / "design" / "JOURNAL.md").write_text("###Malformed entry\n")

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-99"], capture_output=True)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project),
             "branch=issue-99", "base_branch=main"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "warnings" in data
        assert len(data["warnings"]) == 1
        assert "malformed" in data["warnings"][0]

    def test_missing_positional_args(self):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
