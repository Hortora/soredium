"""Tests for work-end/branch_cleanup.py — scaffold cleanup."""

import subprocess
import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(skill_dir))

from branch_cleanup import cleanup_scaffold


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)
    return path


class TestCleanupScaffold:
    def test_removes_meta_and_journal(self, tmp_path):
        ws = init_repo(tmp_path / "workspace")
        design = ws / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: test\n")
        (design / "JOURNAL.md").write_text("# Journal\n")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "scaffold"], capture_output=True)
        result = cleanup_scaffold(str(ws), {})
        assert result == 0
        assert not (design / ".meta").exists()
        assert not (design / "JOURNAL.md").exists()

    def test_removes_epic_file(self, tmp_path):
        ws = init_repo(tmp_path / "workspace")
        design = ws / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: test\n")
        (design / ".epic").write_text("## Issue\nrepo#100\nType: epic\n")
        (design / "JOURNAL.md").write_text("# Journal\n")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "scaffold"], capture_output=True)
        result = cleanup_scaffold(str(ws), {})
        assert result == 0
        assert not (design / ".meta").exists()
        assert not (design / ".epic").exists()
        assert not (design / "JOURNAL.md").exists()

    def test_no_scaffold_files(self, tmp_path):
        ws = init_repo(tmp_path / "workspace")
        result = cleanup_scaffold(str(ws), {})
        assert result == 0

    def test_only_epic_file(self, tmp_path):
        ws = init_repo(tmp_path / "workspace")
        design = ws / "design"
        design.mkdir()
        (design / ".epic").write_text("## Issue\nrepo#100\nType: epic\n")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "scaffold"], capture_output=True)
        result = cleanup_scaffold(str(ws), {})
        assert result == 0
        assert not (design / ".epic").exists()
