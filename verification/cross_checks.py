"""Cross-estate verification checks.

Pure functions that inspect relationships across multiple slots/repos.
No side effects, no fixes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
from slot_io import parse_slot as _parse_slot

from verification import Finding, read_file_safe


def check_duplicate_slots(slots_dir: Path) -> list[Finding]:
    """Detect multiple active slots using the same branch."""
    findings: list[Finding] = []
    if not slots_dir.exists():
        return findings
    branch_map: dict[str, str] = {}
    for slot_dir in sorted(slots_dir.iterdir()):
        if not slot_dir.is_dir() or not slot_dir.name.isdigit():
            continue
        info = _parse_slot(slot_dir)
        if not info or not info.branch:
            continue
        if info.branch in branch_map:
            findings.append(Finding(
                "ERROR", "duplicate-slot",
                f"slots {branch_map[info.branch]} and {slot_dir.name} both use branch {info.branch}",
            ))
        else:
            branch_map[info.branch] = slot_dir.name
    return findings


def check_duplicate_issues(slots_dir: Path) -> list[Finding]:
    """Detect the same issue being worked on in multiple active slots."""
    findings: list[Finding] = []
    if not slots_dir.exists():
        return findings
    issue_map: dict[str, list[str]] = {}
    for slot_dir in sorted(slots_dir.iterdir()):
        if not slot_dir.is_dir() or not slot_dir.name.isdigit():
            continue
        info = _parse_slot(slot_dir)
        if not info:
            continue
        issue_repo = info.issue_repo
        if info.covers:
            nums = re.findall(r'\d+', info.covers)
            for n in nums:
                key = f"{issue_repo}#{n}" if issue_repo else n
                issue_map.setdefault(key, []).append(f"slot {slot_dir.name}")
    for issue_key, locations in sorted(issue_map.items()):
        if len(locations) > 1:
            findings.append(Finding(
                "ERROR", "duplicate-issue",
                f"issue {issue_key} being worked on in {' AND '.join(locations)}",
            ))
    return findings


def check_split_brain(slots_dir: Path, attic_dir: Path) -> list[Finding]:
    """Detect slots that exist in both active and attic directories."""
    findings: list[Finding] = []
    if not slots_dir.exists() or not attic_dir.exists():
        return findings
    active_nums = {
        d.name for d in slots_dir.iterdir()
        if d.is_dir() and d.name.isdigit()
    }
    attic_nums = {
        d.name for d in attic_dir.iterdir()
        if d.is_dir() and d.name.isdigit()
    }
    for num in sorted(active_nums & attic_nums):
        findings.append(Finding(
            "ERROR", "split-brain",
            f"slot {num} exists in BOTH slots/{num}/ AND slots/attic/{num}/",
        ))
    return findings
