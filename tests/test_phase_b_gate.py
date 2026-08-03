"""Tests for work-end/phase_b_gate.py"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

script_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(script_dir))

import phase_b_gate


def _make_stamped_repo(path: Path) -> Path:
    """Create a git repo with a stamp commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m",
                    "chore: branch closed — landed as abc123 on main"],
                   capture_output=True, check=True)
    return path


class TestCheckStamps:
    def test_all_stamped(self, tmp_path):
        slot = tmp_path / "attic" / "72"
        _make_stamped_repo(slot / "engine")
        assert phase_b_gate.check_stamps(slot) == []

    def test_missing_stamp(self, tmp_path):
        slot = tmp_path / "attic" / "72"
        repo = slot / "engine"
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-m", "feat: work"],
                       capture_output=True, check=True)
        assert phase_b_gate.check_stamps(slot) == ["engine"]

    def test_ignores_non_git_dirs(self, tmp_path):
        slot = tmp_path / "attic" / "72"
        (slot / "notes").mkdir(parents=True)
        assert phase_b_gate.check_stamps(slot) == []


class TestCheckPromoted:
    def test_promoted_in_subdir(self, tmp_path):
        slot = tmp_path / "attic" / "72"
        stamp = slot / "work" / "design" / ".artifacts-promoted"
        stamp.parent.mkdir(parents=True)
        stamp.write_text("ok\n")
        assert phase_b_gate.check_promoted(slot) is True

    def test_not_promoted(self, tmp_path):
        slot = tmp_path / "attic" / "72"
        slot.mkdir(parents=True)
        assert phase_b_gate.check_promoted(slot) is False


class TestCheckArchived:
    def test_in_attic(self, tmp_path):
        slot = tmp_path / "worktrees" / "attic" / "72"
        slot.mkdir(parents=True)
        assert phase_b_gate.check_archived(slot) is True

    def test_not_in_attic(self, tmp_path):
        slot = tmp_path / "worktrees" / "72"
        slot.mkdir(parents=True)
        assert phase_b_gate.check_archived(slot) is False


class TestRunGate:
    def test_all_pass(self, tmp_path):
        slot = tmp_path / "worktrees" / "attic" / "72"
        _make_stamped_repo(slot / "engine")
        stamp = slot / "engine" / "design" / ".artifacts-promoted"
        stamp.parent.mkdir(parents=True)
        stamp.write_text("ok\n")
        with patch.object(phase_b_gate, "check_issues", return_value=([], False)):
            result = phase_b_gate.run_gate(slot, [83], "org/repo")
        assert result["gate"] == "pass"

    def test_fail_missing_stamps(self, tmp_path):
        slot = tmp_path / "worktrees" / "attic" / "72"
        repo = slot / "engine"
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-m", "feat: work"],
                       capture_output=True, check=True)
        stamp = slot / "engine" / "design" / ".artifacts-promoted"
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text("ok\n")
        with patch.object(phase_b_gate, "check_issues", return_value=([], False)):
            result = phase_b_gate.run_gate(slot, [83], "org/repo")
        assert result["gate"] == "fail"
        assert "stamps:engine" in result["missing"]

    def test_warn_github_unreachable(self, tmp_path):
        slot = tmp_path / "worktrees" / "attic" / "72"
        _make_stamped_repo(slot / "engine")
        stamp = slot / "engine" / "design" / ".artifacts-promoted"
        stamp.parent.mkdir(parents=True)
        stamp.write_text("ok\n")
        with patch.object(phase_b_gate, "check_issues", return_value=([83], True)):
            result = phase_b_gate.run_gate(slot, [83], "org/repo")
        assert result["gate"] == "warn"
        assert "issues:83" in result["missing"]
        assert result["reason"] == "github_unreachable"

    def test_fail_not_archived(self, tmp_path):
        slot = tmp_path / "worktrees" / "72"
        _make_stamped_repo(slot / "engine")
        stamp = slot / "engine" / "design" / ".artifacts-promoted"
        stamp.parent.mkdir(parents=True)
        stamp.write_text("ok\n")
        with patch.object(phase_b_gate, "check_issues", return_value=([], False)):
            result = phase_b_gate.run_gate(slot, [83], "org/repo")
        assert result["gate"] == "fail"
        assert "archive" in result["missing"]
