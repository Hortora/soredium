#!/usr/bin/env python3
"""
fork_next_branch.py — Create a new branch for the next queue item before closing the current branch.

Reads .plan, advances to next item, creates new branches (workspace + project),
writes advanced .plan + HANDOFF.md to the new workspace branch.

Usage:
    python3 fork_next_branch.py workspace=<path> project=<path> branch=<current> base_branch=main

Output: KEY=value lines
    FORK_BRANCH=<new-branch-name>
    PLAN_ADVANCED=yes
    HANDOFF_COPIED=yes|no
"""

import shutil
import subprocess
import sys
from pathlib import Path

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

_slot_dir = str(Path(__file__).resolve().parent.parent / "work-slot")
if _slot_dir not in sys.path:
    sys.path.insert(0, _slot_dir)


def _git(repo: str, *args: str) -> tuple[bool, str]:
    r = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode == 0, r.stdout.strip()


def _parse_args(argv: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for arg in argv:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k] = v
    return result


def main() -> int:
    args = _parse_args(sys.argv[1:])
    workspace = args.get("workspace", "")
    project = args.get("project", "")
    branch = args.get("branch", "")
    base_branch = args.get("base_branch", "main")

    if not workspace or not project or not branch:
        print("ERROR=missing_args")
        return 1

    ws = Path(workspace)
    plan_path = ws / ".plan"
    if not plan_path.exists():
        print("ERROR=no_plan")
        return 1

    from plan_io import read_plan, has_uncompleted_items

    state = read_plan(plan_path)
    if state is None or not has_uncompleted_items(state):
        print("ERROR=no_remaining_items")
        return 1

    next_item = None
    for item in state.queue_items:
        if not item.completed and not item.active:
            next_item = item
            break
    if next_item is None:
        print("ERROR=no_next_item")
        return 1

    issue_num = str(next_item.number) if next_item.number else ""
    title_slug = next_item.title.lower()
    for ch in "/:?#[]@!$&'()*+,;= ":
        title_slug = title_slug.replace(ch, "-")
    title_slug = title_slug.strip("-")[:40].rstrip("-")
    fork_branch = f"issue-{issue_num}-{title_slug}" if issue_num else f"next-{title_slug}"

    ok, _ = _git(workspace, "checkout", "-b", fork_branch)
    if not ok:
        print(f"ERROR=ws_branch_create_failed branch={fork_branch}")
        return 1

    ok, _ = _git(project, "checkout", "-b", fork_branch)
    if not ok:
        _git(workspace, "checkout", branch)
        print(f"ERROR=proj_branch_create_failed branch={fork_branch}")
        return 1

    try:
        from plan_manager import advance as _advance
        _advance(plan_path)
    except Exception as e:
        print(f"WARN=advance_failed error={e}")

    _git(workspace, "add", ".plan")
    _git(workspace, "commit", "-m", f"chore: advance queue to {next_item.title}")
    print(f"PLAN_ADVANCED=yes")

    handoff = ws / "HANDOFF.md"
    if not handoff.exists():
        for candidate in ws.iterdir():
            if candidate.name.startswith("HANDOFF") and candidate.suffix == ".md":
                handoff = candidate
                break

    if handoff.exists():
        print("HANDOFF_COPIED=yes")
    else:
        print("HANDOFF_COPIED=no")

    _git(workspace, "checkout", branch)
    _git(project, "checkout", branch)

    print(f"FORK_BRANCH={fork_branch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
