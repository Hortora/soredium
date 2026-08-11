"""Tests for work-end/common.py — subdir_prefix."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

from common import subdir_prefix


def _init_git(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
                   capture_output=True)


def test_empty_at_repo_root(tmp_path):
    _init_git(tmp_path)
    assert subdir_prefix(str(tmp_path)) == ""


def test_returns_prefix_for_subdirectory(tmp_path):
    _init_git(tmp_path)
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    assert subdir_prefix(str(subdir)) == "subdir/"


def test_nested_subdirectory(tmp_path):
    _init_git(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert subdir_prefix(str(nested)) == "a/b/"


def test_not_a_git_repo(tmp_path):
    plain = tmp_path / "not-git"
    plain.mkdir()
    assert subdir_prefix(str(plain)) == ""
