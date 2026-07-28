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
    HAS_HANDOFF=yes|no
    HANDOFF_PATH=<path>       (only if HAS_HANDOFF=yes)
    SLOT_PATH=<path>          (only if IN_SLOT=yes)
"""

import re
import sys
from pathlib import Path


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

    if "/worktrees/" in str(project):
        candidate = project.parent / ".slot"
        if candidate.exists():
            in_slot = True
            slot_path = str(candidate)
            content = candidate.read_text()

            in_issue_section = False
            for line in content.splitlines():
                if line.startswith("## Issue"):
                    in_issue_section = True
                    continue
                if line.startswith("## ") and in_issue_section:
                    break
                if in_issue_section and line.strip() == "Type: epic":
                    is_epic = True

            if is_epic:
                batch_numbers = re.findall(
                    r"^### Batch (\d+)", content, re.MULTILINE
                )
                total_batches = len(batch_numbers)

                m = re.search(
                    r"^Current batch:\s*(\d+)", content, re.MULTILINE
                )
                current_batch = m.group(1) if m else "0"
                epic_batch = f"{current_batch} of {total_batches}"

                m = re.search(
                    r"^Current issue:\s*#(\d+)", content, re.MULTILINE
                )
                epic_active_issue = m.group(1) if m else ""

    if not in_slot:
        epic_candidate = workspace / "design" / ".epic"
        if epic_candidate.exists():
            epic_content = epic_candidate.read_text()
            epic_in_issue = False
            for line in epic_content.splitlines():
                if line.startswith("## Issue"):
                    epic_in_issue = True
                    continue
                if line.startswith("## ") and epic_in_issue:
                    break
                if epic_in_issue and line.strip() == "Type: epic":
                    is_epic = True

            if is_epic:
                epic_file_path = str(epic_candidate)

                batch_numbers = re.findall(
                    r"^### Batch (\d+)", epic_content, re.MULTILINE
                )
                total_batches = len(batch_numbers)

                m = re.search(
                    r"^Current batch:\s*(\d+)", epic_content,
                    re.MULTILINE
                )
                current_batch = m.group(1) if m else "0"
                epic_batch = f"{current_batch} of {total_batches}"

                m = re.search(
                    r"^Current issue:\s*#(\d+)", epic_content,
                    re.MULTILINE
                )
                epic_active_issue = m.group(1) if m else ""

    has_handoff = False
    handoff_path = ""
    handoff_candidate = workspace / "HANDOFF.md"
    if handoff_candidate.exists():
        has_handoff = True
        handoff_path = str(handoff_candidate)

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
