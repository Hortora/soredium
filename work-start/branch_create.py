#!/usr/bin/env python3
"""
branch_create.py — Externalized git operations for work-start

Subcommands:

    create-branches <project> <workspace> branch=<name> [base=<base>]
        Create matching branches in project and workspace atomically.
        Project branch from current HEAD (or <base> if provided).
        If project fails: abort, no cleanup.
        If workspace fails: delete project branch, abort.
        Output: CREATED=yes

    commit-scaffold <workspace> branch=<name>
        Stage and commit design/JOURNAL.md and design/.meta, then push.
        Output: COMMITTED=yes, PUSHED=yes|no

Exit codes:
    0  success
    1  error
"""

import subprocess
import sys


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


def create_branches(project: str, workspace: str, branch: str, base: str | None) -> int:
    """Create branches in project and workspace atomically."""
    # Create project branch
    if base:
        ok, err = run_git(project, "checkout", "-b", branch, base)
    else:
        ok, err = run_git(project, "checkout", "-b", branch)

    if not ok:
        print(f"ERROR=project_branch_failed:{err}")
        return 1

    # Create workspace branch
    ok, err = run_git(workspace, "checkout", "-b", branch)
    if not ok:
        # Rollback: return project to previous branch, then delete
        run_git(project, "checkout", "-")
        run_git(project, "branch", "-D", branch)
        print(f"ERROR=workspace_branch_failed:{err}")
        return 1

    print("CREATED=yes")
    return 0


def commit_scaffold(workspace: str, branch: str) -> int:
    """Commit scaffold files and push."""
    ok, _ = run_git(workspace, "add", "design/JOURNAL.md", "design/.meta")
    if not ok:
        print("ERROR=add_failed")
        return 1

    commit_msg = f"init({branch}): scaffold workspace branch"
    ok, _ = run_git(workspace, "commit", "-m", commit_msg)
    if not ok:
        print("ERROR=commit_failed")
        return 1

    # Push with -u (non-fatal)
    push_ok, _ = run_git(workspace, "push", "-u", "origin", branch)

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

    if cmd == "create-branches":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            return 1
        project = sys.argv[2]
        workspace = sys.argv[3]
        kv = parse_kv_args(sys.argv[4:])
        branch = kv.get("branch")
        if not branch:
            print("ERROR=missing_branch")
            return 1
        base = kv.get("base") or None
        return create_branches(project, workspace, branch, base)

    elif cmd == "commit-scaffold":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        workspace = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        branch = kv.get("branch")
        if not branch:
            print("ERROR=missing_branch")
            return 1
        return commit_scaffold(workspace, branch)

    else:
        print("ERROR=unknown_subcommand")
        return 1


if __name__ == "__main__":
    sys.exit(main())
