#!/usr/bin/env python3
"""
Retrospective issue creation operations for retro-issues skill.

Usage: python3 retro_create.py <subcommand> <target> [key=value args...]

Subcommands:
  create-epic <repo> title=<t> body-file=<path>
  create-issue <repo> title=<t> body-file=<path> labels=<csv> close=<yes/no>
  close-issue <repo> issue=<N>
  commit-mapping <project> file=<path>

Output (KEY=value lines):
    ISSUE_NUMBER=<N>
    CLOSED=yes|no
    COMMITTED=yes
    ERROR=<code>

Exit codes:
    0  success
    1  missing args, validation failure, or command error
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], check: bool = True) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        print(f"ERROR=command_failed")
        print(f"ERROR_DETAIL={result.stderr.strip()}")
        sys.exit(result.returncode)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def create_epic(repo: str, title: str, body_file: str) -> None:
    """Create an epic issue via gh CLI."""
    body_path = Path(body_file)
    if not body_path.exists():
        print(f"ERROR=body_file_not_found")
        sys.exit(1)

    with open(body_path) as f:
        body = f.read()

    cmd = [
        "gh", "issue", "create",
        "--repo", repo,
        "--title", title,
        "--label", "epic",
        "--body", body,
    ]

    _, stdout, _ = run_command(cmd)

    # Extract issue number from gh output (format: https://github.com/owner/repo/issues/N)
    issue_url = stdout.strip()
    if not issue_url:
        print("ERROR=no_output")
        sys.exit(1)

    issue_number = issue_url.split("/")[-1]
    print(f"ISSUE_NUMBER={issue_number}")


def create_issue(repo: str, title: str, body_file: str, labels: str, close: str) -> None:
    """Create a regular issue via gh CLI, optionally closing it immediately."""
    body_path = Path(body_file)
    if not body_path.exists():
        print(f"ERROR=body_file_not_found")
        sys.exit(1)

    with open(body_path) as f:
        body = f.read()

    cmd = [
        "gh", "issue", "create",
        "--repo", repo,
        "--title", title,
        "--label", labels,
        "--body", body,
    ]

    _, stdout, _ = run_command(cmd)

    issue_url = stdout.strip()
    if not issue_url:
        print("ERROR=no_output")
        sys.exit(1)

    issue_number = issue_url.split("/")[-1]

    closed = "no"
    if close.lower() == "yes":
        close_cmd = ["gh", "issue", "close", issue_number, "--repo", repo]
        run_command(close_cmd)
        closed = "yes"

    print(f"ISSUE_NUMBER={issue_number}")
    print(f"CLOSED={closed}")


def close_issue(repo: str, issue: str) -> None:
    """Close an existing issue via gh CLI."""
    cmd = ["gh", "issue", "close", issue, "--repo", repo]
    run_command(cmd)
    print("CLOSED=yes")


def commit_mapping(project: str, file: str) -> None:
    """Add and commit the mapping file to git."""
    project_path = Path(project)
    if not project_path.exists():
        print("ERROR=project_not_found")
        sys.exit(1)

    file_path = Path(file)
    if not file_path.exists():
        print("ERROR=file_not_found")
        sys.exit(1)

    # Add the file
    add_cmd = ["git", "-C", str(project_path), "add", str(file_path)]
    run_command(add_cmd)

    # Commit with standard message
    commit_cmd = [
        "git", "-C", str(project_path),
        "commit", "-m", "docs: retrospective issue mapping",
    ]
    run_command(commit_cmd)

    print("COMMITTED=yes")


def parse_kv(args: list[str]) -> dict[str, str]:
    """Parse key=value arguments into a dict."""
    parsed: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            key, val = arg.split("=", 1)
            parsed[key] = val
    return parsed


def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    subcommand = sys.argv[1]
    target = sys.argv[2]
    params = parse_kv(sys.argv[3:])

    if subcommand == "create-epic":
        title = params.get("title")
        body_file = params.get("body-file")
        if not title:
            print("ERROR=missing_title")
            sys.exit(1)
        if not body_file:
            print("ERROR=missing_body_file")
            sys.exit(1)
        create_epic(target, title, body_file)

    elif subcommand == "create-issue":
        title = params.get("title")
        body_file = params.get("body-file")
        labels = params.get("labels")
        close = params.get("close")
        if not title:
            print("ERROR=missing_title")
            sys.exit(1)
        if not body_file:
            print("ERROR=missing_body_file")
            sys.exit(1)
        if not labels:
            print("ERROR=missing_labels")
            sys.exit(1)
        if not close:
            print("ERROR=missing_close")
            sys.exit(1)
        if close not in ("yes", "no"):
            print("ERROR=invalid_close_value")
            sys.exit(1)
        create_issue(target, title, body_file, labels, close)

    elif subcommand == "close-issue":
        issue = params.get("issue")
        if not issue:
            print("ERROR=missing_issue")
            sys.exit(1)
        close_issue(target, issue)

    elif subcommand == "commit-mapping":
        file = params.get("file")
        if not file:
            print("ERROR=missing_file")
            sys.exit(1)
        commit_mapping(target, file)

    else:
        print(f"ERROR=unknown_subcommand")
        sys.exit(1)


if __name__ == "__main__":
    main()
