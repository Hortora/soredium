#!/usr/bin/env python3
"""
Swap a squashed working branch into place for git-squash Step 8. Local only.

Usage: python3 branch_swap.py <project_path> orig=<branch> work=<branch>

What it does:
    1. Keep the original: git branch -m <orig> backup/pre-squash-<orig>-<YYYYMMDD>
    2. Rename work to orig: git branch -m <work> <orig>

It pushes nothing and switches no checkout. A feature branch is never pushed to
a remote (Landing Rules: only the canonical repo publishes, through
project/canonical_sync.py); an off-disk copy of a branch is canonical_sync.backup.

Output (KEY=value lines):
    SWAPPED=yes
    BACKUP=backup/pre-squash-<orig>-<YYYYMMDD>
    CHECKED_OUT=<branch the checkout is on, unchanged by the swap>
    STATUS_CLEAN=yes|no

Error output:
    ERROR=swap_failed
    ERROR_DETAIL=<message>
    BACKUP=<name>  (always reported if backup was created)

Exit codes:
    0  success
    1  missing args or operation failure
"""

import subprocess
import sys
from datetime import datetime


def git(project: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", project] + list(args),
        capture_output=True, text=True,
    )


def fail(message: str, backup: str = "") -> None:
    """Print error and exit. Always report backup name if known."""
    print("ERROR=swap_failed")
    print(f"ERROR_DETAIL={message}")
    if backup:
        print(f"BACKUP={backup}")
    sys.exit(1)


def main() -> int:
    if len(sys.argv) < 2:
        print("ERROR=missing_args")
        print("ERROR_DETAIL=usage: branch_swap.py <project> orig=<branch> work=<branch>")
        sys.exit(1)

    project = sys.argv[1]
    orig = ""
    work = ""

    for arg in sys.argv[2:]:
        if arg.startswith("orig="):
            orig = arg[len("orig="):]
        elif arg.startswith("work="):
            work = arg[len("work="):]

    if not orig or not work:
        print("ERROR=missing_args")
        print("ERROR_DETAIL=orig and work are required")
        sys.exit(1)

    # Verify project is a git repo
    check = git(project, "rev-parse", "--git-dir")
    if check.returncode != 0:
        print("ERROR=not_a_repo")
        print(f"ERROR_DETAIL={project} is not a git repository")
        sys.exit(1)

    datestamp = datetime.now().strftime("%Y%m%d")
    backup_name = f"backup/pre-squash-{orig}-{datestamp}"

    # Step 1: Rename orig to backup
    r = git(project, "branch", "-m", orig, backup_name)
    if r.returncode != 0:
        fail(f"backup rename failed: {r.stderr.strip()}")

    # Step 2: Rename work to orig
    r = git(project, "branch", "-m", work, orig)
    if r.returncode != 0:
        fail(f"work rename failed: {r.stderr.strip()}", backup=backup_name)

    head = git(project, "branch", "--show-current").stdout.strip()
    status_r = git(project, "status", "--short")
    status_clean = "yes" if not status_r.stdout.strip() else "no"

    print("SWAPPED=yes")
    print(f"BACKUP={backup_name}")
    print(f"CHECKED_OUT={head or 'DETACHED'}")
    print(f"STATUS_CLEAN={status_clean}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
