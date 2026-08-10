#!/usr/bin/env python3
"""
work_router.py — Deterministic work lifecycle routing

Usage:
    python3 work_router.py <current_branch> <project_path> <workspace_path>

Output (KEY=VALUE lines):
    ROUTE=start|resume_branch|resume_stack|workspace_dirty
    ON_MAIN=yes|no
    CURRENT_BRANCH=<name>
    IN_SLOT=yes|no
    IS_EPIC=yes|no
    EPIC_BATCH=<N of M>       (only if IS_EPIC=yes)
    EPIC_ACTIVE_ISSUE=<N>     (only if IS_EPIC=yes)
    STACK_DEPTH=<N>
    HAS_HANDOFF=yes|no        (branch-aware: on a feature branch, yes only
                               when HANDOFF.md references this branch's issue)
    HANDOFF_PATH=<path>       (when HANDOFF.md exists, regardless of HAS_HANDOFF)
    SLOT_PATH=<path>          (only if IN_SLOT=yes)
"""

import re
import subprocess
import sys
from pathlib import Path


def _handoff_references_branch(
    workspace: Path, branch_name: str, handoff_filename: str = "HANDOFF.md"
) -> bool:
    """Check if the handoff file references the current branch's issue.

    Checks working tree first (covers feature branch case where HANDOFF.md
    was written on the branch), then falls back to main.
    """
    issue_match = re.match(r"issue-(\d+)", branch_name)
    if not issue_match:
        return True  # non-standard branch — can't determine, assume resume

    issue_num = issue_match.group(1)

    handoff_file = workspace / handoff_filename
    if handoff_file.exists():
        return bool(re.search(rf'#{issue_num}\b', handoff_file.read_text()))

    result = subprocess.run(
        ["git", "-C", str(workspace), "show", f"main:{handoff_filename}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False

    return bool(re.search(rf'#{issue_num}\b', result.stdout))


def detect_state(current_branch: str, project_path: str,
                 workspace_path: str) -> dict[str, str]:
    project = Path(project_path)
    workspace = Path(workspace_path)

    on_main = current_branch == "main"

    project_branch = subprocess.run(
        ["git", "-C", str(project), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip() if str(project) != str(workspace) else current_branch

    stack_file = workspace / "design" / ".pause-stack"
    stack_depth = 0
    if stack_file.exists():
        stack_depth = sum(
            1 for line in stack_file.read_text().splitlines()
            if line.strip().startswith("- branch:")
        )

    in_slot = False
    is_epic = False
    slot_path = ""
    epic_file_path = ""
    epic_batch = ""
    epic_active_issue = ""
    has_plan = False
    plan_path = ""
    plan_active_issue = ""
    plan_position = ""
    plan_batch = ""

    _epic_dir = Path(__file__).parent.parent / "work-slot"
    if str(_epic_dir) not in sys.path:
        sys.path.insert(0, str(_epic_dir))
    from epic_manager import detect as _epic_detect
    from plan_manager import detect as _plan_detect
    from slot_manager import is_slot_path as _is_slot_path

    _lifecycle_dir = Path(__file__).parent.parent / "project"
    if str(_lifecycle_dir) not in sys.path:
        sys.path.insert(0, str(_lifecycle_dir))
    from lifecycle import read_state as _read_state

    if _is_slot_path(str(project)):
        candidate = project.parent / ".slot"
        if candidate.exists():
            in_slot = True
            slot_path = str(candidate)

        plan_info = _plan_detect(project) if in_slot else None
        if plan_info:
            has_plan = True
            plan_path = plan_info["plan_path"]
            plan_active_issue = str(plan_info["active_issue"] or "")
            completed = plan_info.get("completed_count", 0)
            total = plan_info.get("total_count", 0)
            plan_position = f"{completed}/{total}" if total else ""
            plan_batch = plan_info.get("current_batch") or ""

        if not has_plan:
            epic_info = _epic_detect(project.parent) if in_slot else None
            if epic_info:
                is_epic = True
                current = epic_info.get("current_batch", 0)
                total = len(epic_info.get("batches", []))
                epic_batch = f"{current} of {total}" if total else ""
                epic_active_issue = str(epic_info.get("current_issue", ""))

    if not in_slot:
        plan_info = _plan_detect(workspace)
        if plan_info:
            has_plan = True
            plan_path = plan_info["plan_path"]
            plan_active_issue = str(plan_info["active_issue"] or "")
            completed = plan_info.get("completed_count", 0)
            total = plan_info.get("total_count", 0)
            plan_position = f"{completed}/{total}" if total else ""
            plan_batch = plan_info.get("current_batch") or ""

        if not has_plan:
            epic_info = _epic_detect(workspace)
            if epic_info:
                is_epic = True
                epic_file_path = str(epic_info["epic_path"])
                current = epic_info.get("current_batch", 0)
                total = len(epic_info.get("batches", []))
                epic_batch = f"{current} of {total}" if total else ""
                epic_active_issue = str(epic_info.get("current_issue", ""))

    has_handoff = False
    handoff_path = ""
    project_name = Path(project_path).name
    project_handoff = workspace / f"HANDOFF-{project_name}.md"
    generic_handoff = workspace / "HANDOFF.md"

    def _on_main(filename: str) -> bool:
        rc = subprocess.run(
            ["git", "-C", str(workspace), "cat-file", "-e", f"main:{filename}"],
            capture_output=True,
        ).returncode
        return rc == 0

    handoff_candidate = (
        project_handoff if (_on_main(project_handoff.name) or project_handoff.exists()) else (
            generic_handoff if (_on_main(generic_handoff.name) or generic_handoff.exists()) else None
        )
    )
    if handoff_candidate is not None:
        handoff_path = str(handoff_candidate)
        if on_main:
            has_handoff = True
        else:
            has_handoff = _handoff_references_branch(
                workspace, current_branch, handoff_candidate.name
            )

    meta_file = workspace / "design" / ".meta"
    has_meta = meta_file.exists()
    meta_state = _read_state(meta_file) or ""
    workspace_dirty = (
        not on_main
        and not has_meta
        and str(project) != str(workspace)
        and project_branch == "main"
    )

    if on_main:
        route = "resume_stack" if stack_depth > 0 else "start"
    elif workspace_dirty:
        route = "workspace_dirty"
    else:
        route = "resume_branch"

    result = {
        "ROUTE": route,
        "ON_MAIN": "yes" if on_main else "no",
        "CURRENT_BRANCH": current_branch,
        "IN_SLOT": "yes" if in_slot else "no",
        "HAS_PLAN": "yes" if has_plan else "no",
        "IS_EPIC": "yes" if is_epic else "no",
        "STACK_DEPTH": str(stack_depth),
        "HAS_HANDOFF": "yes" if has_handoff else "no",
        "META_STATE": meta_state,
    }
    if workspace_dirty:
        result["WORKSPACE_BRANCH"] = current_branch
        result["PROJECT_BRANCH"] = project_branch
    if plan_path:
        result["PLAN_PATH"] = plan_path
    if plan_active_issue:
        result["PLAN_ACTIVE_ISSUE"] = plan_active_issue
    if plan_position:
        result["PLAN_POSITION"] = plan_position
    if plan_batch:
        result["PLAN_BATCH"] = plan_batch
    if epic_batch:
        result["EPIC_BATCH"] = epic_batch
    if epic_active_issue:
        result["EPIC_ACTIVE_ISSUE"] = epic_active_issue
    if handoff_path:
        result["HANDOFF_PATH"] = handoff_path
    if slot_path:
        result["SLOT_PATH"] = slot_path
    if epic_file_path:
        result["EPIC_PATH"] = epic_file_path

    return result


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 1

    current_branch = sys.argv[1]
    project_path = sys.argv[2]
    workspace_path = sys.argv[3]

    result = detect_state(current_branch, project_path, workspace_path)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
