#!/usr/bin/env python3
"""
epic_manager.py — Epic batch plan operations for work-slot

Subcommands:
  plan <slot-dir>       Parse .slot, return batch plan as JSON
  advance <slot-dir>    Advance to next issue, update .slot + .meta
  status <slot-dir>     Return progress summary as JSON

Operates on .slot's ## Batch Plan section. Separated from
slot_manager.py to enable future single-repo epic support.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path


def parse_batch_plan(slot_dir: Path) -> dict:
    """Parse .slot and extract epic batch plan state."""
    slot_md = slot_dir / ".slot"
    if not slot_md.exists():
        return {"is_epic": False}

    content = slot_md.read_text()

    is_epic = False
    epic_number = ""
    epic_repo = ""

    in_issue = False
    for line in content.splitlines():
        if line.startswith("## Issue"):
            in_issue = True
            continue
        if line.startswith("## ") and in_issue:
            break
        if not in_issue:
            continue
        if line.strip() == "Type: epic":
            is_epic = True
        if "#" in line and not line.startswith("Covers:") and not line.startswith("Type:") and not line.startswith("Safe exit:"):
            parts = line.strip().split("#")
            if len(parts) == 2:
                epic_repo = parts[0].strip()
                epic_number = parts[1].strip()

    if not is_epic:
        return {"is_epic": False}

    batches = _parse_batches(content)

    completed = []
    current_batch = 0
    current_issue = 0
    for batch in batches:
        for issue in batch["issues"]:
            if issue["done"]:
                completed.append(issue["number"])
            elif current_issue == 0:
                current_batch = batch["number"]
                current_issue = issue["number"]

    return {
        "is_epic": True,
        "epic_number": epic_number,
        "epic_repo": epic_repo,
        "batches": batches,
        "current_batch": current_batch,
        "current_issue": current_issue,
        "completed": completed,
    }


def _parse_batches(content: str) -> list[dict]:
    """Extract batch list from ## Batch Plan section."""
    batches = []
    current = None
    in_batch_plan = False

    for line in content.splitlines():
        if line.strip() == "## Batch Plan":
            in_batch_plan = True
            continue
        if line.startswith("## ") and in_batch_plan:
            break
        if not in_batch_plan:
            continue

        m = re.match(r"^### Batch (\d+) — (.+?)(?:\s*←.*)?$", line)
        if m:
            if current:
                batches.append(current)
            current = {
                "number": int(m.group(1)),
                "name": m.group(2).strip(),
                "issues": [],
            }
            continue

        im = re.match(r"^- \[([ x])\] #(\d+) — (.+?)(?:\s*←.*)?$", line)
        if im and current is not None:
            current["issues"].append({
                "number": int(im.group(2)),
                "title": im.group(3).strip(),
                "done": im.group(1) == "x",
            })

    if current:
        batches.append(current)
    return batches


def advance(slot_dir: Path, meta_path: Path | None = None) -> dict:
    """Advance to the next issue. Updates .slot and .meta COVERS."""
    plan = parse_batch_plan(slot_dir)
    if not plan["is_epic"]:
        return {"error": "not an epic slot"}

    current = plan["current_issue"]
    if current == 0:
        return {"error": "no active issue"}

    next_issue = None
    next_title = ""
    next_batch_num = 0
    batch_complete = False
    found_current = False
    current_batch_num = plan["current_batch"]

    for batch in plan["batches"]:
        for issue in batch["issues"]:
            if found_current and next_issue is None:
                next_issue = issue["number"]
                next_title = issue["title"]
                next_batch_num = batch["number"]
            if issue["number"] == current:
                found_current = True
                if issue == batch["issues"][-1]:
                    batch_complete = True

    epic_complete = next_issue is None
    if epic_complete:
        batch_complete = True

    safe_exit = batch_complete

    _rewrite_slot_md(slot_dir, current, next_issue, next_title,
                     next_batch_num, plan["batches"])

    if meta_path and meta_path.exists():
        _update_meta_covers(meta_path, current)

    return {
        "completed": current,
        "next_issue": next_issue,
        "next_issue_title": next_title,
        "batch_complete": batch_complete,
        "epic_complete": epic_complete,
        "safe_exit": safe_exit,
    }


def _rewrite_slot_md(slot_dir: Path, completed: int,
                     next_issue: int | None, next_title: str,
                     next_batch_num: int, batches: list[dict]) -> None:
    """Rewrite .slot with updated checkboxes, markers, and state."""
    slot_md = slot_dir / ".slot"
    content = slot_md.read_text()
    lines = content.splitlines()
    out = []

    for line in lines:
        # Check off the completed issue, remove its ← active marker
        if f"- [ ] #{completed} —" in line:
            line = re.sub(r"\s*← active\s*$", "", line)
            line = line.replace("- [ ]", "- [x]")

        # Remove stale ← current from batch headers
        if line.startswith("### Batch") and "← current" in line:
            line = re.sub(r"\s*← current\s*$", "", line)

        # Add ← active to next issue
        if next_issue and f"- [ ] #{next_issue} —" in line:
            line = re.sub(r"\s*$", "", line) + " ← active"

        # Add ← current to the batch containing next issue
        if next_issue and line.startswith("### Batch"):
            m = re.match(r"^### Batch (\d+)", line)
            if m and int(m.group(1)) == next_batch_num:
                line = line + " ← current"

        # Update Session State
        if line.startswith("Current batch:"):
            line = f"Current batch: {next_batch_num if next_issue else 0}"
        if line.startswith("Current issue:"):
            if next_issue:
                line = f"Current issue: #{next_issue} — {next_title}"
            else:
                line = "Current issue:"

        # Update What to do — Current line
        if line.startswith("Current: Batch"):
            if next_issue:
                for b in batches:
                    if b["number"] == next_batch_num:
                        line = f"Current: Batch {next_batch_num} — {b['name']}"
                        break
            else:
                line = "Current: Epic complete"

        out.append(line)

    # Update Covers line
    result = []
    for line in out:
        if line.startswith("Covers:"):
            existing = line.split(":", 1)[1].strip()
            nums = [n.strip() for n in existing.split(",") if n.strip()]
            s = str(completed)
            if s not in nums:
                nums.append(s)
            line = f"Covers: {','.join(nums)}"
        result.append(line)

    slot_md.write_text("\n".join(result))


def _update_meta_covers(meta_path: Path, issue_number: int) -> None:
    """Append issue_number to covers in .meta."""
    content = meta_path.read_text()
    lines = content.splitlines()
    new_lines = []
    for line in lines:
        if line.startswith("covers:"):
            existing = line.split(":", 1)[1].strip()
            nums = [n.strip() for n in existing.split(",") if n.strip()]
            s = str(issue_number)
            if s not in nums:
                nums.append(s)
            line = f"covers: {','.join(nums)}"
        new_lines.append(line)
    meta_path.write_text("\n".join(new_lines) + "\n")


def status(slot_dir: Path) -> dict:
    """Return epic progress summary."""
    plan = parse_batch_plan(slot_dir)
    if not plan["is_epic"]:
        return {"is_epic": False}

    total_issues = sum(len(b["issues"]) for b in plan["batches"])
    completed_count = len(plan["completed"])
    total_batches = len(plan["batches"])

    completed_batches = sum(
        1 for b in plan["batches"]
        if all(i["done"] for i in b["issues"])
    )

    return {
        "is_epic": True,
        "epic_number": plan["epic_number"],
        "epic_repo": plan["epic_repo"],
        "total_issues": total_issues,
        "completed_count": completed_count,
        "total_batches": total_batches,
        "completed_batches": completed_batches,
        "current_batch": plan["current_batch"],
        "current_issue": plan["current_issue"],
        "safe_exit": completed_batches > 0,
        "batches": plan["batches"],
    }


def write_epic_slot_md(slot_dir: Path, slot_number: int, repos: list[str],
                       branch: str, issue: str, issue_repo: str,
                       batches: list[dict], context: str) -> None:
    """Write .slot with epic batch plan structure."""
    lines = [f"# Slot {slot_number} — {branch}", ""]
    lines.append("## Issue")
    lines.append(f"{issue_repo}#{issue}")
    lines.append("Covers:")
    lines.append("Type: epic")
    lines.append("Safe exit: after any completed batch")
    lines.append("")
    lines.append("## What to do")
    lines.append(f"Epic #{issue} — {context}")
    if batches:
        lines.append(f"Current: Batch 1 — {batches[0]['name']}")
    lines.append("")
    lines.append("## Batch Plan")
    lines.append("")

    first_issue_set = False
    for batch in batches:
        current_marker = " ← current" if batch["number"] == 1 else ""
        lines.append(f"### Batch {batch['number']} — {batch['name']}{current_marker}")
        for issue_item in batch["issues"]:
            active_marker = ""
            if not first_issue_set and batch["number"] == 1:
                active_marker = " ← active"
                first_issue_set = True
            lines.append(f"- [ ] #{issue_item['number']} — {issue_item['title']}{active_marker}")
        lines.append("")

    first_issue_info = batches[0]["issues"][0] if batches and batches[0]["issues"] else None
    lines.append("## Session State")
    lines.append("Current batch: 1")
    if first_issue_info:
        lines.append(f"Current issue: #{first_issue_info['number']} — {first_issue_info['title']}")
    lines.append("Last wrap: slot created")
    lines.append("")
    lines.append("## Repos")
    for i, repo in enumerate(repos):
        primary = " (primary)" if i == 0 else ""
        lines.append(f"- {repo}{primary}")
    lines.append("")
    lines.append("## Created")
    lines.append(f"{date.today().isoformat()}, branch: {branch}")
    lines.append("")
    (slot_dir / ".slot").write_text("\n".join(lines))


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    slot_dir = Path(sys.argv[2])

    if command == "plan":
        result = parse_batch_plan(slot_dir)
        print(json.dumps(result, indent=2))
    elif command == "advance":
        meta_path = None
        if not slot_dir.is_dir():
            print(f"ERROR=slot_dir_not_found path={slot_dir}", file=sys.stderr)
            sys.exit(1)
        for sub in slot_dir.iterdir():
            if not sub.is_dir():
                continue
            candidate = sub / "design" / ".meta"
            if candidate.exists():
                meta_path = candidate
                break
            for ws_sub in sub.iterdir():
                if ws_sub.is_dir():
                    candidate = ws_sub / "design" / ".meta"
                    if candidate.exists():
                        meta_path = candidate
                        break
            if meta_path:
                break
        result = advance(slot_dir, meta_path=meta_path)
        print(json.dumps(result, indent=2))
    elif command == "status":
        result = status(slot_dir)
        print(json.dumps(result, indent=2))
    else:
        print(f"ERROR=unknown_command command={command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
