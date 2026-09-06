"""Shared verification library — pure check functions for lifecycle postconditions.

Check functions take a path/context and return list[Finding].
No side effects, no fixes, no output.
"""
from __future__ import annotations

import os
import subprocess
from typing import NamedTuple


class Finding(NamedTuple):
    severity: str  # ERROR, WARN, INFO
    category: str
    message: str


def git(repo_path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True, text=True, timeout=10,
    )


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
