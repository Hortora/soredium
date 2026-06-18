#!/usr/bin/env python3
"""
Handle branch rename and force push for git-squash Step 8.

Usage: python3 branch_swap.py <project_path> orig=<branch> work=<branch>

What it does:
    1. Create backup: git branch -m <orig> backup/pre-squash-<orig>-<YYYYMMDD>
    2. Rename work to orig: git branch -m <work> <orig>
    3. Set upstream: git branch --set-upstream-to=origin/<orig> <orig>
    4. Force push: git push --force-with-lease origin <orig>
    5. Post-swap verify: git status --short, git log unpushed

Output (KEY=value lines):
    SWAPPED=yes
    BACKUP=backup/pre-squash-<orig>-<YYYYMMDD>
    STATUS_CLEAN=yes|no
    UNPUSHED=<count>

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

    # Step 3: Set upstream (may fail if no remote — that's OK)
    upstream_r = git(project, "branch", "--set-upstream-to", f"origin/{orig}", orig)
    upstream_set = "yes" if upstream_r.returncode == 0 else "no"

    # Step 4: Force push
    r = git(project, "push", "--force-with-lease", "origin", orig)
    push_failed = r.returncode != 0

    # Step 5: Post-swap verify
    status_r = git(project, "status", "--short")
    status_clean = "yes" if not status_r.stdout.strip() else "no"

    log_r = git(project, "log", "--oneline", f"origin/{orig}..{orig}")
    unpushed = 0
    if log_r.returncode == 0 and log_r.stdout.strip():
        unpushed = len(log_r.stdout.strip().splitlines())

    # Report results
    if push_failed:
        # Swap succeeded locally, but push failed — report as success with warning
        print("SWAPPED=yes")
        print(f"BACKUP={backup_name}")
        print(f"UPSTREAM_SET={upstream_set}")
        print(f"STATUS_CLEAN={status_clean}")
        print(f"UNPUSHED={unpushed}")
        print("PUSH_FAILED=yes")
        print(f"PUSH_ERROR={r.stderr.strip()}")
    else:
        print("SWAPPED=yes")
        print(f"BACKUP={backup_name}")
        print(f"UPSTREAM_SET={upstream_set}")
        print(f"STATUS_CLEAN={status_clean}")
        print(f"UNPUSHED={unpushed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
