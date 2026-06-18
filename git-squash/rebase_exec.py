#!/usr/bin/env python3
"""
Execute squash plans non-interactively for git-squash.

Usage: python3 rebase_exec.py <subcommand> <project_path> [args...]

Subcommands:
    single          <project>                           — squash HEAD~1 into HEAD
    multi           <project> base=<sha> todo-file=<p>  — rebase with todo file
    amend-message   <project> message=<msg>             — amend HEAD commit message

Output (KEY=value lines):
    SQUASHED=yes           (single)
    REBASED=yes            (multi)
    COMMITS_BEFORE=N       (multi)
    COMMITS_AFTER=M        (multi)
    AMENDED=yes            (amend-message)

Error output:
    ERROR=<error_code>
    ERROR_DETAIL=<message>

Exit codes:
    0  success
    1  missing args, git failure, or rebase conflict
"""

import os
import shlex
import subprocess
import sys


def git(project: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", project] + list(args),
        capture_output=True, text=True,
    )


def count_commits(project: str, range_spec: str) -> int:
    r = git(project, "rev-list", "--count", range_spec)
    if r.returncode != 0:
        return 0
    return int(r.stdout.strip())


def cmd_single(project: str) -> None:
    """Fast path: squash HEAD~1 into HEAD."""
    # Verify at least 2 commits exist
    r = git(project, "rev-parse", "HEAD~1")
    if r.returncode != 0:
        print("ERROR=single_failed")
        print("ERROR_DETAIL=fewer than 2 commits on branch")
        sys.exit(1)

    r = git(project, "reset", "--soft", "HEAD~1")
    if r.returncode != 0:
        print("ERROR=single_failed")
        print(f"ERROR_DETAIL=reset failed: {r.stderr.strip()}")
        sys.exit(1)

    r = git(project, "commit", "--amend", "--no-edit")
    if r.returncode != 0:
        print("ERROR=single_failed")
        print(f"ERROR_DETAIL=amend failed: {r.stderr.strip()}")
        sys.exit(1)

    print("SQUASHED=yes")


def cmd_multi(project: str, args: list[str]) -> None:
    """Rebase with a provided todo file."""
    base = ""
    todo_file = ""

    for arg in args:
        if arg.startswith("base="):
            base = arg[len("base="):]
        elif arg.startswith("todo-file="):
            todo_file = arg[len("todo-file="):]

    if not base or not todo_file:
        print("ERROR=missing_args")
        print("ERROR_DETAIL=base and todo-file are required")
        sys.exit(1)

    # Count commits before
    head_sha = git(project, "rev-parse", "HEAD").stdout.strip()
    commits_before = count_commits(project, f"{base}..{head_sha}")

    # Execute rebase with the todo file as sequence editor
    env_cmd = f"cp {shlex.quote(str(todo_file))}"
    r = subprocess.run(
        ["git", "-C", project, "rebase", "-i", base],
        capture_output=True, text=True,
        env={**os.environ, "GIT_SEQUENCE_EDITOR": env_cmd},
    )

    if r.returncode != 0:
        # Abort the rebase if it failed
        git(project, "rebase", "--abort")
        print("ERROR=rebase_failed")
        print(f"ERROR_DETAIL={r.stderr.strip()}")
        sys.exit(1)

    # Count commits after
    new_head = git(project, "rev-parse", "HEAD").stdout.strip()
    commits_after = count_commits(project, f"{base}..{new_head}")

    print("REBASED=yes")
    print(f"COMMITS_BEFORE={commits_before}")
    print(f"COMMITS_AFTER={commits_after}")


def cmd_amend_message(project: str, args: list[str]) -> None:
    """Amend the HEAD commit message."""
    message = ""

    for arg in args:
        if arg.startswith("message="):
            message = arg[len("message="):]

    if not message:
        print("ERROR=missing_args")
        print("ERROR_DETAIL=message is required")
        sys.exit(1)

    r = git(project, "commit", "--amend", "-m", message)
    if r.returncode != 0:
        print("ERROR=amend_failed")
        print(f"ERROR_DETAIL={r.stderr.strip()}")
        sys.exit(1)

    print("AMENDED=yes")


def main() -> int:
    if len(sys.argv) < 3:
        print("ERROR=missing_args")
        print("ERROR_DETAIL=usage: rebase_exec.py <subcommand> <project> [args...]")
        sys.exit(1)

    subcommand = sys.argv[1]
    project = sys.argv[2]
    remaining = sys.argv[3:]

    # Verify project is a git repo
    check = git(project, "rev-parse", "--git-dir")
    if check.returncode != 0:
        print("ERROR=not_a_repo")
        print(f"ERROR_DETAIL={project} is not a git repository")
        sys.exit(1)

    if subcommand == "single":
        cmd_single(project)
    elif subcommand == "multi":
        cmd_multi(project, remaining)
    elif subcommand == "amend-message":
        cmd_amend_message(project, remaining)
    else:
        print("ERROR=unknown_subcommand")
        print(f"ERROR_DETAIL=unknown subcommand: {subcommand}")
        sys.exit(1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
