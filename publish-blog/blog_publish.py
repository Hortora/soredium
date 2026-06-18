#!/usr/bin/env python3
"""
Blog publishing operations for publish-blog skill.

Externalised from SKILL.md Step 6, 7, 8 OPERATION blocks.
"""

import sys
import subprocess
from pathlib import Path


def copy_entry(source_path: str, dest_dir: str) -> None:
    """
    Copy a single blog entry file to destination directory.

    Args:
        source_path: Path to source blog entry file
        dest_dir: Destination directory path

    Output:
        COPIED=yes on success
        ERROR=source_not_found if source doesn't exist
        ERROR=copy_failed on copy error
    """
    src = Path(source_path)
    if not src.exists():
        print("ERROR=source_not_found", flush=True)
        sys.exit(1)

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    dest_file = dest / src.name
    try:
        dest_file.write_bytes(src.read_bytes())
        print("COPIED=yes", flush=True)
    except Exception as e:
        print(f"ERROR=copy_failed: {e}", flush=True)
        sys.exit(1)


def commit_destination(dest_repo: str, files_csv: str, message: str) -> None:
    """
    Add, commit, and push files in destination git repo.

    Args:
        dest_repo: Path to destination git repository
        files_csv: Comma-separated list of files to add (relative to repo)
        message: Commit message

    Output:
        COMMITTED=yes, PUSHED=yes/no
    """
    repo_path = Path(dest_repo)
    files = [f.strip() for f in files_csv.split(",") if f.strip()]

    # Add each file
    for file in files:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "add", file],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ERROR=git_add_failed: {result.stderr}", flush=True)
            sys.exit(1)

    # Commit
    result = subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", message],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR=git_commit_failed: {result.stderr}", flush=True)
        sys.exit(1)

    # Push (non-fatal if fails)
    result = subprocess.run(
        ["git", "-C", str(repo_path), "push"],
        capture_output=True,
        text=True,
    )
    pushed = "yes" if result.returncode == 0 else "no"
    print("COMMITTED=yes", flush=True)
    print(f"PUSHED={pushed}", flush=True)


def remove_source(source_repo: str, files_csv: str) -> None:
    """
    Remove published blog entries from source repo.

    Args:
        source_repo: Path to source git repository
        files_csv: Comma-separated list of files to remove (relative to repo)

    Output:
        REMOVED=<count>
    """
    repo_path = Path(source_repo)
    files = [f.strip() for f in files_csv.split(",") if f.strip()]

    # Remove each file with git rm
    removed_count = 0
    for file in files:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rm", file],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ERROR=git_rm_failed: {result.stderr}", flush=True)
            sys.exit(1)
        removed_count += 1

    # Commit the removals
    if removed_count > 0:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "commit", "-m",
             "chore: remove published blog entries"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ERROR=git_commit_failed: {result.stderr}", flush=True)
            sys.exit(1)

    print(f"REMOVED={removed_count}", flush=True)


def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: blog_publish.py <subcommand> [args...]", file=sys.stderr)
        print("Subcommands:", file=sys.stderr)
        print("  copy-entry <source-path> <dest-dir>", file=sys.stderr)
        print("  commit-destination <dest-repo> files=<csv> message=<msg>",
              file=sys.stderr)
        print("  remove-source <source-repo> files=<csv>", file=sys.stderr)
        sys.exit(1)

    subcommand = sys.argv[1]

    if subcommand == "copy-entry":
        if len(sys.argv) != 4:
            print("Usage: copy-entry <source-path> <dest-dir>", file=sys.stderr)
            sys.exit(1)
        copy_entry(sys.argv[2], sys.argv[3])

    elif subcommand == "commit-destination":
        if len(sys.argv) != 5:
            print("Usage: commit-destination <dest-repo> files=<csv> message=<msg>",
                  file=sys.stderr)
            sys.exit(1)
        dest_repo = sys.argv[2]
        files_arg = sys.argv[3]
        message_arg = sys.argv[4]

        if not files_arg.startswith("files="):
            print("ERROR: Second arg must be files=<csv>", file=sys.stderr)
            sys.exit(1)
        if not message_arg.startswith("message="):
            print("ERROR: Third arg must be message=<msg>", file=sys.stderr)
            sys.exit(1)

        files_csv = files_arg[6:]  # Strip "files="
        message = message_arg[8:]  # Strip "message="
        commit_destination(dest_repo, files_csv, message)

    elif subcommand == "remove-source":
        if len(sys.argv) != 4:
            print("Usage: remove-source <source-repo> files=<csv>", file=sys.stderr)
            sys.exit(1)
        source_repo = sys.argv[2]
        files_arg = sys.argv[3]

        if not files_arg.startswith("files="):
            print("ERROR: Second arg must be files=<csv>", file=sys.stderr)
            sys.exit(1)

        files_csv = files_arg[6:]  # Strip "files="
        remove_source(source_repo, files_csv)

    else:
        print(f"ERROR: Unknown subcommand '{subcommand}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
