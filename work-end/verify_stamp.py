#!/usr/bin/env python3
"""
Verify that a branch's source file content actually landed on the target branch
before writing a "chore: branch closed" stamp.

Catches two failure modes:
  1. Squash plans that dropped commit groups, silently losing content
  2. Stacked branches where content landed on an intermediate branch, not main

Usage: python3 verify_stamp.py <project_path> <branch_name> <base_branch>

Output (KEY=value lines):
    VERIFIED=yes            Content landed — safe to stamp
    VERIFIED=no             Content gap detected — DO NOT stamp
    MISSING_FILES=N         Number of source files with diffs
    MISSING_LIST=a.java,b.java   Comma-separated list (when VERIFIED=no)

Error output:
    ERROR=<error_code>
    ERROR_DETAIL=<message>

Exit codes:
    0  success (VERIFIED=yes or VERIFIED=no — both are valid outcomes)
    1  missing args, git error, or other failure
"""

import subprocess
import sys

SOURCE_EXTENSIONS = (
    ".java", ".kt", ".xml", ".yaml", ".yml", ".json",
    ".properties", ".sql", ".py", ".ts", ".tsx", ".js",
    ".jsx", ".css", ".scss", ".html",
)


def git(project: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", project, *args],
        capture_output=True, text=True,
    )


def main() -> int:
    if len(sys.argv) < 4:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=Usage: verify_stamp.py <project> <branch> <base_branch>")
        return 1

    project = sys.argv[1]
    branch = sys.argv[2]
    base_branch = sys.argv[3]

    result = git(project, "rev-parse", "--git-dir")
    if result.returncode != 0:
        print("ERROR=NOT_A_REPO")
        print(f"ERROR_DETAIL={project} is not a git repository")
        return 1

    for ref in (branch, base_branch):
        result = git(project, "rev-parse", "--verify", ref)
        if result.returncode != 0:
            print(f"ERROR=BAD_REF")
            print(f"ERROR_DETAIL=ref '{ref}' does not exist")
            return 1

    result = git(project, "diff", "--name-only", f"{base_branch}...{branch}")
    if result.returncode != 0:
        result = git(project, "diff", "--name-only", base_branch, branch)
        if result.returncode != 0:
            print("ERROR=DIFF_FAILED")
            print(f"ERROR_DETAIL=git diff failed: {result.stderr.strip()}")
            return 1

    branch_files = [
        f for f in result.stdout.strip().split("\n")
        if f and any(f.endswith(ext) for ext in SOURCE_EXTENSIONS)
    ]

    if not branch_files:
        print("VERIFIED=yes")
        print("MISSING_FILES=0")
        return 0

    result = git(project, "diff", base_branch, branch, "--", *branch_files)
    if result.returncode != 0:
        print("ERROR=DIFF_FAILED")
        print(f"ERROR_DETAIL=git diff failed: {result.stderr.strip()}")
        return 1

    if not result.stdout.strip():
        print("VERIFIED=yes")
        print("MISSING_FILES=0")
        return 0

    result = git(project, "diff", "--name-only", base_branch, branch, "--", *branch_files)
    missing = [f for f in result.stdout.strip().split("\n") if f]

    print("VERIFIED=no")
    print(f"MISSING_FILES={len(missing)}")
    print(f"MISSING_LIST={','.join(missing)}")

    print("", file=sys.stderr)
    print(f"Content verification FAILED — {len(missing)} source file(s) on '{branch}'", file=sys.stderr)
    print(f"are not reflected on '{base_branch}':", file=sys.stderr)
    print("", file=sys.stderr)
    for f in missing:
        print(f"  {f}", file=sys.stderr)
    print("", file=sys.stderr)
    print("The squash may have dropped commits. Do NOT stamp this branch.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
