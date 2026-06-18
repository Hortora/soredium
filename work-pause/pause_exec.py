#!/usr/bin/env python3
"""
pause_exec.py — Externalized operations for work-pause

Usage:
    python3 pause_exec.py commit-wip <repo> message=<msg>
    python3 pause_exec.py push-and-stack <workspace> <project> branch=<name> issue=<N> base-branch=<base>

Exit codes:
    0  success
    1  error

Output: KEY=value lines
"""

import sys
import subprocess
from pathlib import Path


def run_git(repo: str, *args: str) -> tuple[bool, str]:
    """Run git command. Returns (success, stdout)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def commit_wip(repo: str, message: str) -> int:
    """
    Check if repo has uncommitted changes. If dirty, commit as WIP.

    Output:
        COMMITTED=yes|clean
    """
    success, status_out = run_git(repo, "status", "--short")
    if not success:
        print("ERROR=git_status_failed")
        return 1

    if not status_out.strip():
        print("COMMITTED=clean")
        return 0

    # Dirty — add and commit
    add_ok, _ = run_git(repo, "add", "-A")
    if not add_ok:
        print("ERROR=git_add_failed")
        return 1

    commit_ok, _ = run_git(repo, "commit", "-m", message)
    if not commit_ok:
        print("ERROR=commit_failed")
        return 1

    print("COMMITTED=yes")
    return 0


def push_and_stack(workspace: str, project: str, branch: str, issue: str, base_branch: str) -> int:
    """
    Push project/workspace branches, checkout base, pull, add stack entry.

    Push failures are non-fatal. Stack push MUST succeed.

    Output:
        STACKED=yes
        PROJECT_PUSHED=yes|no
        WORKSPACE_PUSHED=yes|no
    """
    # Push project branch (non-fatal)
    project_push_ok, _ = run_git(project, "push", "origin", branch)
    print(f"PROJECT_PUSHED={'yes' if project_push_ok else 'no'}")

    # Push workspace branch (non-fatal)
    workspace_push_ok, _ = run_git(workspace, "push", "origin", branch)
    print(f"WORKSPACE_PUSHED={'yes' if workspace_push_ok else 'no'}")

    # Checkout base in project
    checkout_ok, _ = run_git(project, "checkout", base_branch)
    if not checkout_ok:
        print("ERROR=project_checkout_failed")
        return 1

    # Checkout main in workspace
    ws_checkout_ok, _ = run_git(workspace, "checkout", "main")
    if not ws_checkout_ok:
        print("ERROR=workspace_checkout_failed")
        return 1

    # Pull project (skip if no upstream configured)
    has_upstream, _ = run_git(project, "rev-parse", "--abbrev-ref", "@{u}")
    if has_upstream:
        pull_ok, _ = run_git(project, "pull", "--rebase")
        if not pull_ok:
            print("ERROR=project_pull_failed")
            return 1

    # Pull workspace (skip if no remote)
    has_remote, _ = run_git(workspace, "remote", "get-url", "origin")
    if has_remote:
        ws_pull_ok, _ = run_git(workspace, "pull", "--rebase", "origin", "main")
        if not ws_pull_ok:
            print("ERROR=workspace_pull_failed")
            return 1

    # Push stack entry
    stack_file = Path(workspace) / "design" / ".pause-stack"
    stack_script = Path.home() / ".claude" / "skills" / "project-init" / "stack.py"

    try:
        result = subprocess.run(
            ["python3", str(stack_script), "push", str(stack_file),
             f"branch={branch}", f"issue={issue}"],
            capture_output=True,
            text=True,
            check=True
        )
        # Parse STACK_DEPTH from output
        depth = None
        for line in result.stdout.splitlines():
            if line.startswith("STACK_DEPTH="):
                depth = line.split("=")[1]
                break

        if depth is None:
            print("ERROR=stack_depth_missing")
            return 1

        # Add, commit, push stack change
        add_ok, _ = run_git(workspace, "add", "design/.pause-stack")
        if not add_ok:
            print("ERROR=stack_add_failed")
            return 1

        commit_msg = f"chore: pause {branch} — stack depth {depth}"
        commit_ok, _ = run_git(workspace, "commit", "-m", commit_msg)
        if not commit_ok:
            print("ERROR=stack_commit_failed")
            return 1

        # Push stack commit (only if remote is configured)
        has_ws_remote, _ = run_git(workspace, "remote", "get-url", "origin")
        if has_ws_remote:
            push_stack_ok, _ = run_git(workspace, "push")
            if not push_stack_ok:
                # If stack push fails, abort by popping the entry
                subprocess.run(
                    ["python3", str(stack_script), "pop", str(stack_file), branch],
                    check=False
                )
                print("ERROR=stack_push_failed")
                return 1

        print("STACKED=yes")
        return 0

    except subprocess.CalledProcessError:
        print("ERROR=stack_script_failed")
        return 1


def parse_kv_args(args: list[str]) -> dict[str, str]:
    """Parse key=value arguments into dict."""
    result = {}
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

    if cmd == "commit-wip":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            return 1
        repo = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        message = kv.get("message")
        if not message:
            print("ERROR=missing_message")
            return 1
        return commit_wip(repo, message)

    elif cmd == "push-and-stack":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            return 1
        workspace = sys.argv[2]
        project = sys.argv[3]
        kv = parse_kv_args(sys.argv[4:])
        branch = kv.get("branch")
        issue = kv.get("issue")
        base_branch = kv.get("base-branch", "main")
        if not branch or not issue:
            print("ERROR=missing_branch_or_issue")
            return 1
        return push_and_stack(workspace, project, branch, issue, base_branch)

    else:
        print("ERROR=unknown_subcommand")
        return 1


if __name__ == "__main__":
    sys.exit(main())
