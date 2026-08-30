"""Tests for scripts/audit_duplicate_commits.py"""

import subprocess
import sys
from pathlib import Path

import pytest

AUDIT_SCRIPT = str(Path(__file__).parent.parent / "scripts" / "audit_duplicate_commits.py")


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True,
    )


def _init_repo(tmp_path, name="repo"):
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True)
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "checkout", "-b", "main")
    (repo / "init.txt").write_text("init")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


class TestAuditDuplicateCommits:

    def test_detects_duplicates(self, tmp_path):
        repo = _init_repo(tmp_path)
        _git(repo, "checkout", "-b", "feature")
        (repo / "feat.txt").write_text("feature work")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "feat: add feature")
        feat_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "main")
        _git(repo, "cherry-pick", feat_sha)
        _git(repo, "merge", "feature", "--no-edit")

        result = subprocess.run(
            [sys.executable, AUDIT_SCRIPT, str(repo)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "PAIRS=1" in result.stdout
        assert "STATUS=dirty" in result.stdout

    def test_clean_repo(self, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "a.txt").write_text("a")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "add a")

        result = subprocess.run(
            [sys.executable, AUDIT_SCRIPT, str(repo)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "STATUS=clean" in result.stdout

    def test_same_message_different_content_not_flagged(self, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "file.txt").write_text("version 1")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "update file")
        (repo / "file.txt").write_text("version 2")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "update file")

        result = subprocess.run(
            [sys.executable, AUDIT_SCRIPT, str(repo)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "STATUS=clean" in result.stdout
