#!/usr/bin/env python3
"""Push to upstream remote when fork is ahead. Falls back to PR creation."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args


def _git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, timeout=30,
    )


def run(project: str, base_branch: str = "main") -> int:
    upstream = _git(project, "remote", "get-url", "upstream")
    if upstream.returncode != 0:
        print("SKIPPED=no_upstream")
        return 0

    _git(project, "fetch", "upstream", base_branch)
    _git(project, "fetch", "origin", base_branch)

    ahead = _git(project, "rev-list", "--count",
                 f"upstream/{base_branch}..origin/{base_branch}")
    if ahead.returncode != 0 or ahead.stdout.strip() == "0":
        print("SKIPPED=no_drift")
        return 0

    fork_ahead = ahead.stdout.strip()
    print(f"FORK_AHEAD={fork_ahead}")

    push = _git(project, "push", "upstream", f"origin/{base_branch}:refs/heads/{base_branch}", "--no-verify")
    if push.returncode == 0:
        print(f"PUSHED=upstream/{base_branch}")
        return 0

    pr = subprocess.run(
        ["gh", "pr", "create", "--repo", upstream.stdout.strip().replace(".git", "").split("github.com/")[-1],
         "--head", f"{base_branch}", "--base", base_branch,
         "--title", f"chore: sync fork ({fork_ahead} commits)",
         "--body", "Automated fork sync from work-end."],
        capture_output=True, text=True, timeout=30,
    )
    if pr.returncode == 0:
        print(f"PR_CREATED={pr.stdout.strip()}")
        return 0

    print(f"WARN=upstream_sync_failed push={push.stderr.strip()} pr={pr.stderr.strip()}")
    return 0


def main() -> int:
    args = parse_args(sys.argv[1:])
    project = args.get("project", "")
    base = args.get("base_branch", "main")
    if not project:
        print("ERROR=missing_project")
        return 1
    return run(project, base)


if __name__ == "__main__":
    sys.exit(main())
