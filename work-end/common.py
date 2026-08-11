#!/usr/bin/env python3
"""Shared utilities for work-end scripts."""

import subprocess


def parse_args(args: list[str]) -> dict[str, str]:
    """Parse key=value arguments from CLI args."""
    result: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k.strip()] = v.strip()
    return result


def subdir_prefix(cwd: str) -> str:
    """Get path from git repo root to cwd, for correcting <rev>:<path> lookups.

    Returns empty string when cwd IS the repo root.
    """
    result = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-prefix"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def detect_topology(project: str) -> tuple[str, str]:
    """Returns (fork_remote, blessed_remote).

    Fork model (origin=fork, upstream=blessed): returns ("origin", "upstream")
    Direct model (origin=blessed, no upstream): returns ("origin", "")
    No remotes: returns ("", "")
    """
    result = subprocess.run(
        ["git", "-C", project, "remote", "get-url", "upstream"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        return "origin", "upstream"
    result = subprocess.run(
        ["git", "-C", project, "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        return "origin", ""
    return "", ""
