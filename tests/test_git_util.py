"""Tests for project/git_util.py."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


def test_git_successful_command(tmp_path):
    """Happy path: run git status in a valid repo."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    from git_util import git

    result = git(tmp_path, "status")

    assert result.returncode == 0
    assert isinstance(result.stdout, str)


def test_git_accepts_str_path(tmp_path):
    """Path types: str works the same as Path."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    from git_util import git

    result = git(str(tmp_path), "status")

    assert result.returncode == 0


def test_git_nonexistent_repo(tmp_path):
    """Edge case: non-existent repo returns non-zero, no exception."""
    from git_util import git

    result = git(tmp_path / "does-not-exist", "status")

    assert result.returncode != 0


def test_git_invalid_command(tmp_path):
    """Edge case: invalid git subcommand returns non-zero, no exception."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    from git_util import git

    result = git(tmp_path, "not-a-real-command")

    assert result.returncode != 0


def test_git_timeout(tmp_path, monkeypatch):
    """Timeout: exceeding timeout raises TimeoutExpired."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    from git_util import git

    with pytest.raises(subprocess.TimeoutExpired):
        git(tmp_path, "status", timeout=0)


def test_git_custom_timeout(tmp_path):
    """Timeout: caller can override default."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    from git_util import git

    result = git(tmp_path, "status", timeout=60)

    assert result.returncode == 0


def test_git_captures_stderr(tmp_path):
    """Stderr is captured as a string."""
    from git_util import git

    result = git(tmp_path / "nope", "status")

    assert isinstance(result.stderr, str)
    assert len(result.stderr) > 0
