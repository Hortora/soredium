"""Composed verification checks for lifecycle events.

Each function runs the checks appropriate for a lifecycle gate,
returns list[Finding]. Callers decide whether to block or warn.
"""
from __future__ import annotations

from pathlib import Path

from verification import Finding, is_git_repo
from verification.slot_checks import (
    check_absolute_symlinks,
    check_claude_md_paths,
    check_workspace_content_in_project,
)
from verification.repo_checks import (
    check_stuck_close_state,
)


def post_create_slot(slot_dir: Path) -> list[Finding]:
    """Run after slot creation. Checks all clones for isolation violations.

    Only isolation violations (symlinks, paths) are ERROR-severity.
    Workspace clone health is checked by validate_slot_wksp separately.
    """
    findings: list[Finding] = []
    for entry in sorted(slot_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if is_git_repo(entry):
            findings.extend(check_absolute_symlinks(entry, slot_dir))
            findings.extend(check_claude_md_paths(entry / "CLAUDE.md", slot_dir))
            if not (entry / ".workspace").exists():
                findings.extend(check_workspace_content_in_project(entry / "CLAUDE.md"))
    return findings


def pre_work_start(workspace: Path, branch: str = "") -> list[Finding]:
    """Run before scaffold creation. Catches stuck state and mismatches."""
    findings: list[Finding] = []
    plan = workspace / ".plan"
    if plan.exists():
        findings.extend(check_stuck_close_state(plan))
        if branch:
            from verification.slot_checks import check_plan_branch_matches_slot
            findings.extend(check_plan_branch_matches_slot(plan, branch))
    return findings


def pre_work_start_attic_guard(slot_path: Path) -> list[Finding]:
    """Block work-start if the slot directory is in attic/."""
    findings: list[Finding] = []
    if slot_path and "attic" in slot_path.parts:
        findings.append(Finding(
            "ERROR", "in-attic",
            f"slot is in attic — cannot start work in archived slot",
        ))
    return findings
