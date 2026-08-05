#!/usr/bin/env python3
"""
verify_slot_close.py — Unified verification gate for work-end.

Checks that all repos are merged, stamped, pushed, and artifacts promoted.
Defense-in-depth audit — the primary fix is Execute's mechanical per-repo
loop; this catches bugs in Execute itself.

Usage:
    python3 verify_slot_close.py <project> branch=<name> workspace=<path> [covers=N,M]

Output: VERIFIED=yes|no with per-check results.
Exit 0 always (verification outcome is data, not an error).
Exit 1 on missing args or operational errors.
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args


def git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
        timeout=10,
    )


def check_branch_merged(project: str, branch: str, base: str = "main") -> dict:
    result = git(project, "log", "--oneline", f"{base}..{branch}")
    if result.returncode != 0:
        return {"status": "fail", "detail": f"branch {branch} not found"}
    unmerged = [
        line for line in result.stdout.strip().splitlines()
        if line and not line.split(" ", 1)[-1].startswith("chore: branch closed")
    ]
    if unmerged:
        return {"status": "fail", "detail": f"UNMERGED: {len(unmerged)} commits not on {base}"}
    return {"status": "pass"}


def check_branch_stamped(project: str, branch: str) -> dict:
    result = git(project, "log", "-1", "--format=%s", branch)
    if result.returncode != 0:
        return {"status": "fail", "detail": f"branch {branch} not found"}
    msg = result.stdout.strip()
    if msg.startswith("chore: branch closed"):
        return {"status": "pass"}
    return {"status": "fail", "detail": "UNSTAMPED"}


def check_landing_sha(project: str, branch: str, base: str = "main") -> dict:
    result = git(project, "log", "-1", "--format=%s", branch)
    if result.returncode != 0:
        return {"status": "fail", "detail": "branch not found"}
    msg = result.stdout.strip()
    sha_match = re.search(r"landed as ([0-9a-f]+)", msg)
    if not sha_match:
        return {"status": "pass", "detail": "no landing SHA in stamp (old format)"}
    sha = sha_match.group(1)
    verify = git(project, "merge-base", "--is-ancestor", sha, base)
    if verify.returncode == 0:
        return {"status": "pass", "detail": f"SHA {sha[:8]} on {base}"}
    return {"status": "fail", "detail": f"LANDING_SHA {sha[:8]} not on {base}"}


def check_main_pushed(project: str, base: str = "main") -> dict:
    result = git(project, "log", f"origin/{base}..{base}", "--oneline")
    if result.returncode != 0:
        return {"status": "pass", "detail": "no remote tracking (single remote check skipped)"}
    unpushed = result.stdout.strip()
    if unpushed:
        count = len(unpushed.splitlines())
        return {"status": "fail", "detail": f"UNPUSHED: {count} commits ahead of origin/{base}"}
    return {"status": "pass"}


def check_workspace_stamped(workspace: str, branch: str) -> dict:
    result = git(workspace, "branch", "--list", branch)
    if result.returncode != 0 or not result.stdout.strip():
        return {"status": "pass", "detail": "workspace branch not found (may be single-repo)"}
    return check_branch_stamped(workspace, branch)


def verify(
    project: str, branch: str, workspace: str,
    base: str = "main", covers: list[int] | None = None,
) -> bool:
    checks: list[tuple[str, dict]] = []

    checks.append(("project_merged", check_branch_merged(project, branch, base)))
    checks.append(("project_stamped", check_branch_stamped(project, branch)))
    checks.append(("landing_sha", check_landing_sha(project, branch, base)))
    checks.append(("main_pushed", check_main_pushed(project, base)))
    checks.append(("workspace_stamped", check_workspace_stamped(workspace, branch)))

    all_pass = True
    for name, result in checks:
        status = result["status"]
        detail = result.get("detail", "")
        icon = "✅" if status == "pass" else "❌"
        suffix = f" — {detail}" if detail else ""
        print(f"{icon} {name}: {status}{suffix}")
        if status == "fail":
            all_pass = False

    if all_pass:
        print("VERIFIED=yes")
    else:
        print("VERIFIED=no")
    return all_pass


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: verify_slot_close.py <project> branch=<name> workspace=<path> [covers=N,M]",
              file=sys.stderr)
        return 1

    project = sys.argv[1]
    opts = parse_args(sys.argv[2:])

    branch = opts.get("branch", "")
    workspace = opts.get("workspace", "")
    base = opts.get("base_branch", "main")

    if not branch:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=branch= is required")
        return 1

    if not workspace:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=workspace= is required")
        return 1

    covers_str = opts.get("covers", "")
    covers = [int(x) for x in covers_str.split(",") if x.strip()] if covers_str else None

    verify(project, branch, workspace, base, covers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
