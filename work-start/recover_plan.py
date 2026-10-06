#!/usr/bin/env python3
"""
recover_plan.py — Detect and recover .plan from the last-closed branch.

Checks if the last-worked branch (via worklog DB) has a .plan with
remaining items. If so, outputs the plan content and branch name
so the LLM can offer to carry it forward.

Usage:
    python3 recover_plan.py workspace=<path> project=<path> branch=<current>

Output:
    ORPHANED_PLAN=yes|no
    ORPHANED_BRANCH=<branch-name>
    ORPHANED_REMAINING=<count>
    ORPHANED_NEXT=<next-item-title>
    PLAN_CONTENT=<base64-encoded .plan content>
    HANDOFF_CONTENT=<base64-encoded HANDOFF.md content>
"""

import base64
import subprocess
import sys
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

try:
    import worklog as _wl
except ImportError:
    _wl = None


def _git(repo: str, *args: str) -> tuple[bool, str]:
    r = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, timeout=10,
    )
    return r.returncode == 0, r.stdout.strip()


def _git_show(repo: str, ref: str, path: str) -> str | None:
    ok, content = _git(repo, "show", f"{ref}:{path}")
    return content if ok else None


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
    current_branch = args.get("branch", "")

    if not workspace or not project:
        print("ORPHANED_PLAN=no")
        return 0

    ws_plan = Path(workspace) / ".plan"
    if ws_plan.exists():
        print("ORPHANED_PLAN=no")
        return 0

    if _wl is None:
        print("ORPHANED_PLAN=no")
        return 0

    conn = _wl.connect()
    try:
        rows = conn.execute(
            "SELECT e.event_type, wi.branch FROM events e "
            "JOIN work_items wi ON e.work_item_id = wi.id "
            "JOIN repos r ON wi.repo_id = r.id "
            "WHERE r.path = ? AND e.event_type = 'work-end' "
            "ORDER BY e.id DESC LIMIT 1",
            (project,),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()

    if not rows:
        print("ORPHANED_PLAN=no")
        return 0

    last_branch = rows[0]["branch"]
    if last_branch == current_branch:
        print("ORPHANED_PLAN=no")
        return 0

    plan_content = _git_show(workspace, last_branch, ".plan")
    if not plan_content:
        print("ORPHANED_PLAN=no")
        return 0

    import tempfile
    from plan_io import read_plan, has_uncompleted_items
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".plan", delete=False) as f:
            f.write(plan_content)
            tmp = Path(f.name)
        state = read_plan(tmp)
        tmp.unlink(missing_ok=True)
    except Exception:
        state = None

    if state is None or not has_uncompleted_items(state):
        print("ORPHANED_PLAN=no")
        return 0

    remaining = 0
    next_title = ""
    for item in state.queue_items:
        if not item.completed:
            remaining += 1
            if not item.active and not next_title:
                next_title = item.title

    import json
    marker = Path(workspace) / ".orphaned-plan"
    marker_data = {
        "branch": last_branch,
        "remaining": remaining,
        "next_title": next_title,
        "plan_content": plan_content,
    }
    handoff_content = _git_show(workspace, last_branch, "HANDOFF.md")
    if handoff_content:
        marker_data["handoff_content"] = handoff_content
    marker.write_text(json.dumps(marker_data))

    print("ORPHANED_PLAN=yes")
    print(f"ORPHANED_BRANCH={last_branch}")
    print(f"ORPHANED_REMAINING={remaining}")
    print(f"ORPHANED_NEXT={next_title}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
