#!/usr/bin/env python3
"""
handover_commit.py — Externalized git operations for handover

Subcommands:

    commit <workspace> [file=HANDOFF.md]
        Commit HANDOFF.md on the current branch.
        Output: COMMITTED=yes|skipped

    commit-to-main <workspace> branch=<current> [file=HANDOFF.md]
        Legacy alias — commits on the current branch (same as commit).
        Kept for backward compatibility with callers that pass branch=.

Exit codes:
    0  success
    1  error
"""

import subprocess
import sys
from datetime import date


def run_git(repo: str, *args: str) -> tuple[bool, str]:
    """Run git command. Returns (success, stdout)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def commit_handoff(workspace: str, handoff_file: str = "HANDOFF.md") -> int:
    """Commit HANDOFF.md on the current branch."""
    today = date.today().isoformat()
    commit_msg = f"docs: session handover {today}"

    ok, _ = run_git(workspace, "add", handoff_file)
    if not ok:
        print("ERROR=add_failed")
        return 1

    ok, _ = run_git(workspace, "commit", "-m", commit_msg)
    if not ok:
        print("COMMITTED=skipped")
        return 0

    print("COMMITTED=yes")
    return 0


def parse_kv_args(args: list[str]) -> dict[str, str]:
    """Parse key=value arguments into dict."""
    result: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            key, _, val = arg.partition("=")
            result[key] = val
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("ERROR=missing_subcommand")
        return 1

    cmd = sys.argv[1]

    if cmd in ("commit", "commit-to-main"):
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        workspace = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        handoff_file = kv.get("file", "HANDOFF.md")
        return commit_handoff(workspace, handoff_file)

    else:
        print("ERROR=unknown_subcommand")
        return 1


if __name__ == "__main__":
    sys.exit(main())
