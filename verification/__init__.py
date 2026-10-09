"""Shared verification library — pure check functions for lifecycle postconditions.

Check functions take a path/context and return list[Finding].
No side effects, no fixes, no output.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
from git_util import git as _canonical_git  # noqa: E402


class Finding(NamedTuple):
    severity: str  # ERROR, WARN, INFO
    category: str
    message: str


def git(repo_path, *args: str) -> subprocess.CompletedProcess:
    return _canonical_git(repo_path, *args, timeout=10)


def is_git_repo(path) -> bool:
    r = git(path, "rev-parse", "--git-dir")
    return r.returncode == 0


def read_file_safe(path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def readlink_safe(path) -> str | None:
    try:
        return os.readlink(str(path))
    except OSError:
        return None
