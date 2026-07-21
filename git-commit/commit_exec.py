#!/usr/bin/env python3
"""
commit_exec.py — Externalized git operations for git-commit

Subcommands:

    commit <project> message=<msg> files=<csv>
        Stage listed files and commit with the given message.
        Output: COMMITTED=yes, SHA=<sha>
        Error:  ERROR=nothing_to_commit

    squash <project>
        Soft-reset HEAD~1 to combine with previous commit.
        Output: SQUASHED=yes
        Error:  ERROR=no_parent

    stage-docs <project> files=<csv>
        Stage documentation files (CLAUDE.md, README.md, etc.).
        Output: STAGED=<count>

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


def commit(project: str, message: str, files: list[str]) -> int:
    """Stage files and commit."""
    if not files:
        print("ERROR=no_files")
        return 1

    for f in files:
        ok, _ = run_git(project, "add", f)
        if not ok:
            print(f"ERROR=add_failed:{f}")
            return 1

    # Check something is actually staged
    ok, diff_out = run_git(project, "diff", "--staged", "--stat")
    if ok and not diff_out.strip():
        print("ERROR=nothing_to_commit")
        return 1

    ok, _ = run_git(project, "commit", "-m", message)
    if not ok:
        print("ERROR=nothing_to_commit")
        return 1

    ok, sha = run_git(project, "rev-parse", "HEAD")
    if not ok:
        print("ERROR=sha_failed")
        return 1

    print("COMMITTED=yes")
    print(f"SHA={sha}")
    return 0


def squash(project: str) -> int:
    """Soft-reset HEAD~1 to combine with previous commit."""
    # Check HEAD has a parent
    ok, _ = run_git(project, "rev-parse", "HEAD~1")
    if not ok:
        print("ERROR=no_parent")
        return 1

    ok, _ = run_git(project, "reset", "--soft", "HEAD~1")
    if not ok:
        print("ERROR=reset_failed")
        return 1

    print("SQUASHED=yes")
    return 0


def stage_docs(project: str, files: list[str]) -> int:
    """Stage documentation files."""
    if not files:
        print("STAGED=0")
        return 0

    count = 0
    for f in files:
        ok, _ = run_git(project, "add", f)
        if ok:
            count += 1

    print(f"STAGED={count}")
    return 0


def sync_lockfile(project: str) -> int:
    """Check for staged package.json and sync yarn.lock if needed."""
    ok, staged = run_git(project, "diff", "--cached", "--name-only")
    if not ok:
        print("LOCKFILE_SYNC=skip")
        return 0

    has_package_json = any("package.json" in f for f in staged.splitlines())
    if not has_package_json:
        print("LOCKFILE_SYNC=skip")
        return 0

    import os
    yarn_lock = os.path.join(project, "yarn.lock")
    if not os.path.exists(yarn_lock):
        print("LOCKFILE_SYNC=skip")
        return 0

    result = subprocess.run(
        ["yarn", "install"],
        capture_output=True,
        text=True,
        cwd=project,
    )
    if result.returncode != 0:
        print(f"LOCKFILE_SYNC=error")
        print(f"YARN_STDERR={result.stderr.strip()[:200]}")
        return 1

    ok, diff = run_git(project, "diff", "--name-only", "--", "yarn.lock")
    if ok and diff.strip():
        run_git(project, "add", "yarn.lock")
        print("LOCKFILE_SYNC=staged")
    else:
        print("LOCKFILE_SYNC=unchanged")
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

    if cmd == "commit":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        project = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        message = kv.get("message")
        files_csv = kv.get("files", "")
        if not message:
            print("ERROR=missing_message")
            return 1
        files = [f.strip() for f in files_csv.split(",") if f.strip()]
        return commit(project, message, files)

    elif cmd == "squash":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        project = sys.argv[2]
        return squash(project)

    elif cmd == "stage-docs":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        project = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        files_csv = kv.get("files", "")
        files = [f.strip() for f in files_csv.split(",") if f.strip()]
        return stage_docs(project, files)

    elif cmd == "sync-lockfile":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        project = sys.argv[2]
        return sync_lockfile(project)

    else:
        print("ERROR=unknown_subcommand")
        return 1


if __name__ == "__main__":
    sys.exit(main())
