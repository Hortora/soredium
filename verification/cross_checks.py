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


def check_zombie_slots(slots_dir: Path) -> list[Finding]:
    """Detect active slots where all project branches are stamped/closed."""
    from verification import git
    findings: list[Finding] = []
    for slot_dir in sorted(slots_dir.iterdir()):
        if not slot_dir.is_dir() or slot_dir.name in ("attic", "quarantine"):
            continue
        slot_file = slot_dir / ".slot"
        if not slot_file.exists():
            continue
        parsed = _parse_slot(slot_file)
        branch = parsed.get("branch", "")
        if not branch:
            continue
        all_stamped = True
        has_repos = False
        for clone in sorted(slot_dir.iterdir()):
            if not clone.is_dir() or not (clone / ".git").exists():
                continue
            if clone.name.startswith("wsp-"):
                continue
            has_repos = True
            r = git(clone, "log", "-1", "--format=%s", branch)
            if r.returncode == 0 and r.stdout.strip():
                if not r.stdout.strip().startswith("chore: branch closed"):
                    all_stamped = False
                    break
            else:
                r2 = git(clone, "branch", "--show-current")
                if r2.returncode != 0 or r2.stdout.strip() != "main":
                    all_stamped = False
                    break
        if has_repos and all_stamped:
            findings.append(Finding(
                "WARN", "zombie-slot",
                f"slot {slot_dir.name} ({branch}): all branches stamped but slot not archived",
            ))
    return findings


def check_dangling_plans(slots_dir: Path) -> list[Finding]:
    """Detect .plan files with state: active but no corresponding branch."""
    from verification import git
    findings: list[Finding] = []
    for slot_dir in sorted(slots_dir.iterdir()):
        if not slot_dir.is_dir() or slot_dir.name in ("attic", "quarantine"):
            continue
        for plan_path in slot_dir.rglob(".plan"):
            if plan_path.stat().st_size == 0:
                continue
            text = plan_path.read_text()
            if "state: active" not in text:
                continue
            branch_line = ""
            for line in text.splitlines():
                if line.startswith("branch:"):
                    branch_line = line.split(":", 1)[1].strip()
                    break
            if not branch_line or branch_line == "main":
                continue
            plan_parent = plan_path.parent
            if not (plan_parent / ".git").exists():
                continue
            r = git(plan_parent, "branch", "--list", branch_line)
            if r.returncode == 0 and not r.stdout.strip():
                findings.append(Finding(
                    "WARN", "dangling-plan",
                    f"slot {slot_dir.name}: .plan references {branch_line} but branch doesn't exist",
                ))
    return findings
