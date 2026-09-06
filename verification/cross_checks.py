"""Cross-estate verification checks.

Pure functions that inspect relationships across multiple slots/repos.
No side effects, no fixes.
"""
from __future__ import annotations

import re
from pathlib import Path

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
        slot_file = slot_dir / ".slot"
        content = read_file_safe(slot_file)
        if content is None:
            continue
        for line in content.splitlines():
            if line.startswith("# Slot") and "—" in line:
                branch = line.split("—", 1)[1].strip()
                if branch in branch_map:
                    findings.append(Finding(
                        "ERROR", "duplicate-slot",
                        f"slots {branch_map[branch]} and {slot_dir.name} both use branch {branch}",
                    ))
                else:
                    branch_map[branch] = slot_dir.name
                break
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
        slot_file = slot_dir / ".slot"
        content = read_file_safe(slot_file)
        if content is None:
            continue
        issue_repo = ""
        for line in content.splitlines():
            if line.startswith("casehubio/") or line.startswith("Hortora/"):
                issue_repo = line.split("#")[0].strip()
            if line.startswith("Covers:"):
                nums = re.findall(r'\d+', line.split(":", 1)[1])
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
