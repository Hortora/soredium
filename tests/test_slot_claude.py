"""Tests for work-slot/slot_claude.py"""

import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_claude


class TestClaudeProjectMatching:
    def test_exact_match(self):
        assert slot_claude._claude_project_matches(
            "-path-worktrees-1", "-path-worktrees-1"
        ) is True

    def test_subdirectory_match(self):
        assert slot_claude._claude_project_matches(
            "-path-worktrees-1-engine", "-path-worktrees-1"
        ) is True

    def test_no_false_positive_on_prefix_number(self):
        """Slot 1 must not match slot 10, 11, 100, etc."""
        assert slot_claude._claude_project_matches(
            "-path-worktrees-10", "-path-worktrees-1"
        ) is False
        assert slot_claude._claude_project_matches(
            "-path-worktrees-10-engine", "-path-worktrees-1"
        ) is False

    def test_no_match_on_unrelated(self):
        assert slot_claude._claude_project_matches(
            "-path-worktrees-2-engine", "-path-worktrees-1"
        ) is False


class TestRelocateClaudeProjectsRelativePath:
    """Regression: relative slot_dir paths must resolve to absolute before encoding."""

    def test_relocate_writes_pid_with_relative_path(self, tmp_path, monkeypatch):
        """Relative paths still write the PID file correctly."""
        slot_abs = tmp_path / "family" / "slots" / "1"
        slot_abs.mkdir(parents=True)

        dest_abs = tmp_path / "family" / "slots" / "attic" / "1"
        dest_abs.mkdir(parents=True)

        slot_rel = Path("family") / "slots" / "1"
        dest_rel = Path("family") / "slots" / "attic" / "1"
        monkeypatch.chdir(tmp_path)

        slot_claude.relocate_claude_projects(slot_rel, dest_rel)

        pid_file = dest_abs / ".archived-by-pid"
        assert pid_file.exists()
        pid = int(pid_file.read_text().strip())
        assert pid > 0

    def test_remove_matches_when_slot_dir_is_relative(self, tmp_path, monkeypatch):
        slot_abs = tmp_path / "family" / "slots" / "1"
        slot_abs.mkdir(parents=True)
        repo = slot_abs / "engine"
        repo.mkdir()

        fake_home = tmp_path / "home"
        claude_projects = fake_home / ".claude" / "projects"
        claude_projects.mkdir(parents=True)
        proj_dir = claude_projects / str(slot_abs / "engine").replace("/", "-")
        proj_dir.mkdir()
        (proj_dir / "session.jsonl").write_text("[]")

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        slot_rel = Path("family") / "slots" / "1"
        monkeypatch.chdir(tmp_path)

        removed = slot_claude.remove_claude_projects(slot_rel)

        assert removed == 1, "relative path must still find the Claude project dir"
        assert not proj_dir.exists()
