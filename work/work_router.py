#!/usr/bin/env python3
"""
work_router.py — Deterministic work lifecycle routing

Usage:
    python3 work_router.py <current_branch> <project_path> <workspace_path>

Output (KEY=VALUE lines):
    ROUTE=start|resume_branch|resume_stack
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
    """Check if the handoff file on workspace main references the current branch's issue."""
    issue_match = re.match(r"issue-(\d+)", branch_name)
    if not issue_match:
        return True  # non-standard branch — can't determine, assume resume

    issue_num = issue_match.group(1)
    result = subprocess.run(
        ["git", "-C", str(workspace), "show", f"main:{handoff_filename}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False  # can't read — treat as first session

    return f"#{issue_num}" in result.stdout


def detect_state(current_branch: str, project_path: str,
                 workspace_path: str) -> dict[str, str]:
    project = Path(project_path)
    workspace = Path(workspace_path)

    on_main = current_branch == "main"

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

    _epic_dir = Path(__file__).parent.parent / "work-slot"
    if str(_epic_dir) not in sys.path:
        sys.path.insert(0, str(_epic_dir))
    from epic_manager import detect as _epic_detect
    from slot_manager import is_slot_path as _is_slot_path

    if _is_slot_path(str(project)):
        candidate = project.parent / ".slot"
        if candidate.exists():
            in_slot = True
            slot_path = str(candidate)

        epic_info = _epic_detect(project.parent) if in_slot else None
        if epic_info:
            is_epic = True
            current = epic_info.get("current_batch", 0)
            total = len(epic_info.get("batches", []))
            epic_batch = f"{current} of {total}" if total else ""
            epic_active_issue = str(epic_info.get("current_issue", ""))

    if not in_slot:
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
    handoff_candidate = project_handoff if project_handoff.exists() else (
        generic_handoff if generic_handoff.exists() else None
    )
    if handoff_candidate is not None:
        handoff_path = str(handoff_candidate)
        if on_main:
            has_handoff = True
        else:
            has_handoff = _handoff_references_branch(
                workspace, current_branch, handoff_candidate.name
            )

    if on_main:
        route = "resume_stack" if stack_depth > 0 else "start"
    else:
        route = "resume_branch"

    result = {
        "ROUTE": route,
        "ON_MAIN": "yes" if on_main else "no",
        "CURRENT_BRANCH": current_branch,
        "IN_SLOT": "yes" if in_slot else "no",
        "IS_EPIC": "yes" if is_epic else "no",
        "STACK_DEPTH": str(stack_depth),
        "HAS_HANDOFF": "yes" if has_handoff else "no",
    }
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
