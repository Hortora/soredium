"""Canonical git command runner for all pipeline code."""
import subprocess
from pathlib import Path


def git(repo: Path | str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a git command against a repo. Never raises on non-zero exit."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout,
    )
