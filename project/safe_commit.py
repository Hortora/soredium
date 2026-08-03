#!/usr/bin/env python3
"""
safe_commit.py — Branch-guarded commits to workspace main.

Generalised from handover_commit.py's commit-to-main pattern.
Ensures files are committed to main regardless of the current branch,
using stash to preserve uncommitted work.

Usage:
    python3 safe_commit.py commit-to-main <repo> files=<csv> message=<msg>

Output:
    COMMITTED=yes
    PUSHED=yes|no
"""

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path


def _run_git(repo: str, *args: str) -> tuple[bool, str]:
    """Run git command. Returns (success, stdout)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True, text=True, check=False,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def _current_branch(repo: str) -> str:
    ok, branch = _run_git(repo, "branch", "--show-current")
    return branch if ok else ""


@contextmanager
def ensure_on_main(repo: str):
    """Context manager that switches to main, yields, then restores the original branch.

    Stashes uncommitted changes before switching and pops on return.
    Yields True if switch succeeded, False if it failed (caller should not proceed).
    """
    original = _current_branch(repo)
    if original == "main":
        yield True
        return

    _run_git(repo, "stash", "--include-untracked")

    ok, _ = _run_git(repo, "checkout", "main")
    if not ok:
        _run_git(repo, "stash", "pop")
        yield False
        return

    try:
        yield True
    finally:
        _run_git(repo, "checkout", original)
        _run_git(repo, "stash", "pop")


def commit_file_to_main(repo: str, files_csv: str, message: str) -> int:
    """Commit one or more files to main, regardless of current branch.

    files_csv: comma-separated relative paths.
    Reads file content before switching branches, writes it on main.
    Returns 0 on success, 1 on error.
    """
    import tempfile, shutil

    files = [f.strip() for f in files_csv.split(",") if f.strip()]
    original = _current_branch(repo)
    repo_path = Path(repo)

    # Read file contents before any branch switch
    file_contents: dict[str, bytes] = {}
    for f in files:
        src = repo_path / f
        if not src.exists():
            print(f"ERROR=file_not_found file={f}")
            return 1
        file_contents[f] = src.read_bytes()

    if original != "main":
        _run_git(repo, "stash", "--include-untracked")

        ok, _ = _run_git(repo, "checkout", "main")
        if not ok:
            _run_git(repo, "checkout", original)
            _run_git(repo, "stash", "pop")
            print("ERROR=checkout_main_failed")
            return 1

        _run_git(repo, "pull", "--rebase", "origin", "main")

    # Write file contents on main
    for f, content in file_contents.items():
        dest = repo_path / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        ok, _ = _run_git(repo, "add", f)
        if not ok:
            if original != "main":
                _run_git(repo, "checkout", original)
                _run_git(repo, "stash", "pop")
            print(f"ERROR=add_failed file={f}")
            return 1

    ok, _ = _run_git(repo, "commit", "-m", message)
    if not ok:
        if original != "main":
            _run_git(repo, "checkout", original)
            _run_git(repo, "stash", "pop")
        print("ERROR=commit_failed")
        return 1

    push_ok, _ = _run_git(repo, "push")

    if original != "main":
        _run_git(repo, "checkout", original)
        _run_git(repo, "stash", "pop")

    print("COMMITTED=yes")
    print(f"PUSHED={'yes' if push_ok else 'no'}")
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: safe_commit.py commit-to-main <repo> files=<csv> message=<msg>")
        return 1

    cmd = sys.argv[1]
    if cmd != "commit-to-main":
        print(f"ERROR=unknown_subcommand cmd={cmd}")
        return 1

    repo = sys.argv[2]
    kv = {}
    for arg in sys.argv[3:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            kv[k] = v

    files = kv.get("files", "")
    message = kv.get("message", "")
    if not files or not message:
        print("ERROR=missing_args (files and message required)")
        return 1

    return commit_file_to_main(repo, files, message)


if __name__ == "__main__":
    sys.exit(main())
