#!/usr/bin/env python3
"""
close_resume.py — Detect and report interrupted close sequences.

Reads .close-progress and reports which steps completed vs remaining.
Used by work-end and the work router to offer resume from the last
completed step.

Usage:
    python3 close_resume.py <workspace> [meta_state=closing:*]

Output:
    INTERRUPTED=yes|no
    COMPLETED=N
    REMAINING=N
    NEXT_STEP=<step_name>
    BRANCH=<branch from .close-progress>
    STEPS_DONE=step1,step2,...
    STEPS_REMAINING=step3,step4,...
"""

import sys
from pathlib import Path

_work_end = Path(__file__).resolve().parent
sys.path.insert(0, str(_work_end))

from close_progress import read_close_progress

CLOSE_VISIBLE_STEPS = [
    "code_review", "branch_audit_conformance", "branch_audit_coherence",
    "branch_audit_structure", "branch_audit_robustness",
    "loose_ends", "forcing_function",
    "sweep_config", "forage", "protocol", "update_claude_md",
    "impl_doc_sync", "adr", "write_content",
    "promote", "trajectory", "rebase", "squash", "land",
    "close_issues", "verify",
    "arc42_scan", "session_rename", "garden_feedback", "notes",
]

STEP_LABELS = {
    "code_review": "Code review",
    "branch_audit_conformance": "Conformance audit",
    "branch_audit_coherence": "Coherence audit",
    "branch_audit_structure": "Structure audit",
    "branch_audit_robustness": "Robustness audit",
    "loose_ends": "Loose ends",
    "forcing_function": "Forcing function",
    "sweep_config": "Sweep config",
    "forage": "Forage SWEEP",
    "protocol": "Protocol SWEEP",
    "update_claude_md": "CLAUDE.md sync",
    "impl_doc_sync": "Doc sync",
    "adr": "ADR",
    "write_content": "Diary entry",
    "promote": "Promote artifacts",
    "trajectory": "Trajectory",
    "rebase": "Rebase",
    "squash": "Squash",
    "land": "Land",
    "close_issues": "Close issues",
    "verify": "Verify",
    "arc42_scan": "ARC42 scan",
    "session_rename": "Session rename",
    "garden_feedback": "Garden feedback",
    "notes": "Notes",
}


def detect_resume(workspace: Path) -> dict[str, str]:
    progress = read_close_progress(workspace)

    if not progress:
        return {"INTERRUPTED": "no"}

    branch = progress.get("_branch", "")
    done = []
    remaining = []
    next_step = ""

    for step in CLOSE_VISIBLE_STEPS:
        status = progress.get(step, "")
        if status in ("done", "skipped"):
            done.append(step)
        else:
            remaining.append(step)
            if not next_step:
                next_step = step

    if not done:
        return {"INTERRUPTED": "no"}

    return {
        "INTERRUPTED": "yes",
        "COMPLETED": str(len(done)),
        "REMAINING": str(len(remaining)),
        "NEXT_STEP": next_step,
        "BRANCH": branch,
        "STEPS_DONE": ",".join(done),
        "STEPS_REMAINING": ",".join(remaining),
    }


def format_resume_prompt(result: dict[str, str]) -> str:
    if result.get("INTERRUPTED") != "yes":
        return ""

    done = result.get("STEPS_DONE", "").split(",")
    remaining = result.get("STEPS_REMAINING", "").split(",")
    next_step = result.get("NEXT_STEP", "")
    branch = result.get("BRANCH", "unknown")

    lines = [
        f"Previous close on branch '{branch}' was interrupted.",
        f"  Completed: {len(done)} steps",
        f"  Remaining: {len(remaining)} steps",
        f"  Next step: {STEP_LABELS.get(next_step, next_step)}",
        "",
        "  Done:",
    ]
    for s in done:
        lines.append(f"    ✅ {STEP_LABELS.get(s, s)}")
    lines.append("")
    lines.append("  Remaining:")
    for s in remaining:
        lines.append(f"    ⬜ {STEP_LABELS.get(s, s)}")

    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: close_resume.py <workspace>", file=sys.stderr)
        sys.exit(1)

    workspace = Path(sys.argv[1])
    result = detect_resume(workspace)

    for k, v in result.items():
        print(f"{k}={v}")

    if result.get("INTERRUPTED") == "yes":
        print()
        print(format_resume_prompt(result))


if __name__ == "__main__":
    main()
