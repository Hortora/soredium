#!/usr/bin/env python3
"""
Collect per-commit classification data for git-squash Steps 3a-3i.
Called AFTER filter-repo (SHAs are stable).

Usage: python3 commit_gather.py <project_path> range=<base..head>

Output: JSON to stdout with per-commit data and repo-level metadata.

Error output (stderr):
    ERROR=<error_code>

Exit codes:
    0  success
    1  missing args, git failure, or parse error
"""

import json
import re
import shutil
import subprocess
import sys
from typing import Any


def git(project: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", project] + list(args),
        capture_output=True, text=True,
    )


def git_out(project: str, *args: str) -> str:
    r = git(project, *args)
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def parse_issue_refs(text: str) -> list[dict[str, Any]]:
    """Extract Closes/Refs/Fixes #N references from commit text."""
    refs = []
    for m in re.finditer(r'(Closes|Refs|Fixes|closes|refs|fixes)\s+#(\d+)', text):
        refs.append({"type": m.group(1).capitalize(), "number": int(m.group(2))})
    return refs


def parse_stat_summary(stat_output: str) -> tuple[int, int]:
    """Parse insertions/deletions from git show --stat summary line."""
    ins, dels = 0, 0
    # The last line looks like: "3 files changed, 45 insertions(+), 3 deletions(-)"
    m = re.search(r'(\d+)\s+insertion', stat_output)
    if m:
        ins = int(m.group(1))
    m = re.search(r'(\d+)\s+deletion', stat_output)
    if m:
        dels = int(m.group(1))
    return ins, dels


def is_conventional_commit(subject: str) -> bool:
    """Check if subject matches conventional commit pattern (type: or type(scope):)."""
    return bool(re.match(r'^[a-z]+(\([^)]+\))?!?: ', subject))


def gather_commits(project: str, range_spec: str) -> list[dict[str, Any]]:
    """Gather per-commit data for the given range."""
    # Get commit list with structured format
    fmt = "%H%x00%s%x00%b%x00%ae%x00%aI%x00---END---"
    log_result = git(project, "log", f"--format={fmt}", range_spec)
    if log_result.returncode != 0:
        print(f"ERROR=log_failed", file=sys.stderr)
        sys.exit(1)

    raw = log_result.stdout.strip()
    if not raw:
        return []

    commits = []
    for block in raw.split("---END---"):
        block = block.strip()
        if not block:
            continue
        parts = block.split("\x00")
        if len(parts) < 5:
            continue

        sha = parts[0].strip()
        subject = parts[1].strip()
        body = parts[2].strip()
        author = parts[3].strip()
        date = parts[4].strip()

        # Files changed
        files_out = git_out(project, "show", "--name-only", "--format=", sha)
        files = [f for f in files_out.splitlines() if f.strip()] if files_out else []

        # Insertions/deletions
        stat_out = git_out(project, "show", "--stat", "--format=", sha)
        insertions, deletions = parse_stat_summary(stat_out)

        # Issue refs from subject + body
        full_text = f"{subject}\n{body}"
        issue_refs = parse_issue_refs(full_text)

        # Patch ID
        show_result = git(project, "show", sha)
        patch_id = ""
        if show_result.returncode == 0:
            pid_result = subprocess.run(
                ["git", "patch-id", "--stable"],
                input=show_result.stdout,
                capture_output=True, text=True,
            )
            if pid_result.returncode == 0 and pid_result.stdout.strip():
                patch_id = pid_result.stdout.strip().split()[0]

        commits.append({
            "sha": sha,
            "subject": subject,
            "body": body,
            "author": author,
            "date": date,
            "files": files,
            "insertions": insertions,
            "deletions": deletions,
            "issue_refs": issue_refs,
            "patch_id": patch_id,
        })

    return commits


def check_conventional(project: str, range_spec: str) -> bool:
    """Check if >=80% of last 20 commits before range use conventional commit format."""
    base = range_spec.split("..")[0]
    log_out = git_out(project, "log", "--format=%s", "-20", base)
    if not log_out:
        return False
    subjects = [s for s in log_out.splitlines() if s.strip()]
    if not subjects:
        return False
    conv_count = sum(1 for s in subjects if is_conventional_commit(s))
    return (conv_count / len(subjects)) >= 0.8


def get_pr_info(project: str) -> dict[str, Any] | None:
    """Try to get PR info via gh CLI. Returns None if unavailable."""
    if not shutil.which("gh"):
        return None
    try:
        r = subprocess.run(
            ["gh", "pr", "view", "--json", "body,title,number,baseRefName"],
            capture_output=True, text=True, cwd=project, timeout=10,
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        return {
            "number": data.get("number"),
            "title": data.get("title", ""),
            "body": data.get("body", ""),
            "base": data.get("baseRefName", ""),
        }
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError):
        return None


def main() -> int:
    if len(sys.argv) < 2:
        print("ERROR=missing_args", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]
    range_spec = ""

    for arg in sys.argv[2:]:
        if arg.startswith("range="):
            range_spec = arg[len("range="):]

    if not range_spec:
        print("ERROR=missing_range", file=sys.stderr)
        sys.exit(1)

    # Verify project is a git repo
    check = git(project, "rev-parse", "--git-dir")
    if check.returncode != 0:
        print("ERROR=not_a_repo", file=sys.stderr)
        sys.exit(1)

    commits = gather_commits(project, range_spec)
    is_conventional = check_conventional(project, range_spec)
    pr = get_pr_info(project)

    result = {
        "range": range_spec,
        "commit_count": len(commits),
        "is_conventional": is_conventional,
        "pr": pr,
        "commits": commits,
    }

    json.dump(result, sys.stdout, indent=2)
    print()  # trailing newline
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
