#!/usr/bin/env python3
"""
handover_commit.py — Externalized git operations for handover

Subcommands:

    commit-to-main <workspace> branch=<current>
        Commit HANDOFF.md to workspace main, even when on a branch.
        If branch != main: stash, checkout main, pull --rebase,
            add HANDOFF.md, commit, push, checkout <branch>, stash pop.
        If branch == main: pull --rebase, add HANDOFF.md, commit, push.
        Output: COMMITTED=yes, PUSHED=yes|no

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


def commit_to_main(workspace: str, branch: str) -> int:
    """Commit HANDOFF.md to workspace main."""
    today = date.today().isoformat()
    commit_msg = f"docs: session handover {today}"

    if branch != "main":
        # Stash current work
        run_git(workspace, "stash")

        # Switch to main
        ok, _ = run_git(workspace, "checkout", "main")
        if not ok:
            # Restore original branch
            run_git(workspace, "checkout", branch)
            run_git(workspace, "stash", "pop")
            print("ERROR=checkout_main_failed")
            return 1

        # Pull latest
        run_git(workspace, "pull", "--rebase", "origin", "main")

        # Add and commit
        ok, _ = run_git(workspace, "add", "HANDOFF.md")
        if not ok:
            run_git(workspace, "checkout", branch)
            run_git(workspace, "stash", "pop")
            print("ERROR=add_failed")
            return 1

        ok, _ = run_git(workspace, "commit", "-m", commit_msg)
        if not ok:
            run_git(workspace, "checkout", branch)
            run_git(workspace, "stash", "pop")
            print("ERROR=commit_failed")
            return 1

        # Push (non-fatal)
        push_ok, _ = run_git(workspace, "push")

        # Return to original branch
        run_git(workspace, "checkout", branch)
        run_git(workspace, "stash", "pop")

        print("COMMITTED=yes")
        print(f"PUSHED={'yes' if push_ok else 'no'}")
        return 0

    else:
        # Already on main
        run_git(workspace, "pull", "--rebase", "origin", "main")

        ok, _ = run_git(workspace, "add", "HANDOFF.md")
        if not ok:
            print("ERROR=add_failed")
            return 1

        ok, _ = run_git(workspace, "commit", "-m", commit_msg)
        if not ok:
            print("ERROR=commit_failed")
            return 1

        push_ok, _ = run_git(workspace, "push")

        print("COMMITTED=yes")
        print(f"PUSHED={'yes' if push_ok else 'no'}")
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

    if cmd == "commit-to-main":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        workspace = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        branch = kv.get("branch")
        if not branch:
            print("ERROR=missing_branch")
            return 1
        return commit_to_main(workspace, branch)

    else:
        print("ERROR=unknown_subcommand")
        return 1


if __name__ == "__main__":
    sys.exit(main())
