#!/usr/bin/env python3
"""
epic_manager.py — Epic batch plan operations

Subcommands:
  plan <epic-path>      Parse epic file, return batch plan as JSON
  advance <epic-path>   Advance to next issue, update file + .meta
  status <epic-path>    Return progress summary as JSON
  check <epic-path>     Output KEY=VALUE epic state for gates
  tick <epic-path>      Tick GitHub epic checkboxes (issue-repo=, epic=, issues=)
  write <epic-path>     Write a new .epic file (workspace=, issue=, slug=,
                        issue-repo=, context=, batches=<JSON>)

Operates on the ## Batch Plan section of .slot or .epic files.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path


def parse_batch_plan(epic_path: Path) -> dict:
    """Parse an epic file (.slot or .epic) and extract batch plan state."""
    if not epic_path.exists():
        return {"is_epic": False}

    content = epic_path.read_text()

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


def detect(path: Path) -> dict | None:
    """Find and parse an epic file from the given path.

    Search order:
    1. path/design/.epic (single-repo workspace)
    2. path/.slot with Type: epic (slot directory)
    3. path.parent/.slot with Type: epic (project inside slot)
    """
    candidates = [
        path / "design" / ".epic",
        path / ".slot",
        path.parent / ".slot",
    ]
    for candidate in candidates:
        if candidate.exists():
            result = parse_batch_plan(candidate)
            if result.get("is_epic"):
                result["epic_path"] = candidate
                return result
    return None


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


def advance(epic_path: Path, meta_path: Path | None = None) -> dict:
    """Advance to the next issue. Updates epic file and .meta COVERS."""
    plan = parse_batch_plan(epic_path)
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

    _rewrite_epic_file(epic_path, current, next_issue, next_title,
                       next_batch_num, plan["batches"])

    return {
        "completed": current,
        "next_issue": next_issue,
        "next_issue_title": next_title,
        "batch_complete": batch_complete,
        "epic_complete": epic_complete,
        "safe_exit": safe_exit,
        "epic_number": plan["epic_number"],
        "epic_repo": plan["epic_repo"],
    }


def _rewrite_epic_file(epic_path: Path, completed: int,
                       next_issue: int | None, next_title: str,
                       next_batch_num: int, batches: list[dict]) -> None:
    """Rewrite epic file with updated checkboxes, markers, and state."""
    content = epic_path.read_text()
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

    epic_path.write_text("\n".join(result))


def status(epic_path: Path) -> dict:
    """Return epic progress summary."""
    plan = parse_batch_plan(epic_path)
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
        "safe_exit": _is_at_batch_boundary(plan, completed_batches),
        "batches": plan["batches"],
    }


def _is_at_batch_boundary(plan: dict, completed_batches: int) -> bool:
    """True when at a batch boundary — no partially-completed batch."""
    if completed_batches == 0:
        return False
    current_issue = plan["current_issue"]
    if current_issue == 0:
        return True
    current_batch_num = plan["current_batch"]
    for batch in plan["batches"]:
        if batch["number"] == current_batch_num:
            if not batch["issues"]:
                return True
            first_issue = batch["issues"][0]
            return first_issue["number"] == current_issue and not first_issue["done"]
    return False


def write_epic_file(epic_path: Path, heading: str,
                    repos: list[str] | None, issue: str,
                    issue_repo: str, batches: list[dict],
                    context: str) -> None:
    """Write an epic file (.slot or .epic) with batch plan structure."""
    lines = [heading, ""]
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
    lines.append("Last wrap: epic created")
    lines.append("")

    if repos is not None:
        lines.append("## Repos")
        for i, repo in enumerate(repos):
            primary = " (primary)" if i == 0 else ""
            lines.append(f"- {repo}{primary}")
        lines.append("")
        lines.append("## Created")
        lines.append(f"{date.today().isoformat()}")
        lines.append("")

    epic_path.write_text("\n".join(lines))


def write_epic_slot_md(slot_dir: Path, slot_number: int, repos: list[str],
                       branch: str, issue: str, issue_repo: str,
                       batches: list[dict], context: str) -> None:
    """Write .slot with epic batch plan structure (slot convenience)."""
    heading = f"# Slot {slot_number} — {branch}"
    write_epic_file(slot_dir / ".slot", heading, repos, issue,
                    issue_repo, batches, context)


def write_epic(workspace: Path, issue: str, slug: str,
               issue_repo: str, batches: list[dict],
               context: str) -> None:
    """Write .epic for single-repo epic (no Repos section)."""
    epic_path = workspace / "design" / ".epic"
    epic_path.parent.mkdir(parents=True, exist_ok=True)
    heading = f"# Epic #{issue} — {slug}"
    write_epic_file(epic_path, heading, repos=None, issue=issue,
                    issue_repo=issue_repo, batches=batches,
                    context=context)


def _tick_checkboxes_in_body(body: str, issues: list[int]) -> str:
    """Replace - [ ] #N with - [x] #N for each issue number."""
    lines = body.splitlines()
    result = []
    for line in lines:
        for n in issues:
            if re.match(rf"^- \[ \] #{n}\b", line) or re.match(rf"^- \[ \] https://github\.com/.+/issues/{n}\b", line):
                line = line.replace("- [ ]", "- [x]", 1)
                break
        result.append(line)
    return "\n".join(result) + ("\n" if body.endswith("\n") else "")


def tick_epic_checkboxes(issue_repo: str, epic_number: int,
                         completed_issues: list[int]) -> bool:
    """Tick checkboxes on the GitHub epic issue body. Returns True on success."""
    import subprocess as _sp
    try:
        r = _sp.run(
            ["gh", "api", f"repos/{issue_repo}/issues/{epic_number}",
             "--jq", ".body"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return False
        body = r.stdout
        updated = _tick_checkboxes_in_body(body, completed_issues)
        if updated == body:
            return True
        r = _sp.run(
            ["gh", "api", "-X", "PATCH",
             f"repos/{issue_repo}/issues/{epic_number}",
             "-f", f"body={updated}"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _parse_kv_args(args: list[str]) -> dict:
    """Parse key=value arguments from CLI."""
    result = {}
    for arg in args:
        if "=" in arg:
            k, v = arg.split("=", 1)
            result[k] = v
    return result


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    epic_path = Path(sys.argv[2])

    if command == "plan":
        result = parse_batch_plan(epic_path)
        print(json.dumps(result, indent=2))
    elif command == "advance":
        meta_path = None
        epic_dir = epic_path.parent
        # Single-repo: .meta is sibling of .epic in workspace/design/
        sibling_meta = epic_dir / ".meta"
        if sibling_meta.exists():
            meta_path = sibling_meta
        elif epic_dir.is_dir():
            # Slot: search subdirectories for .meta
            for sub in epic_dir.iterdir():
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
        result = advance(epic_path, meta_path=meta_path)
        print(json.dumps(result, indent=2))
    elif command == "status":
        result = status(epic_path)
        print(json.dumps(result, indent=2))
    elif command == "check":
        result = status(epic_path)
        if not result.get("is_epic"):
            print("IS_EPIC=no")
        else:
            total = result["total_issues"]
            completed = result["completed_count"]
            epic_complete = total > 0 and completed == total
            print("IS_EPIC=yes")
            print(f"EPIC_COMPLETE={'yes' if epic_complete else 'no'}")
            print(f"SAFE_EXIT={'yes' if result['safe_exit'] else 'no'}")
            print(f"CURRENT_BATCH={result['current_batch']}")
            print(f"TOTAL_BATCHES={result['total_batches']}")
            print(f"ACTIVE_ISSUE={result['current_issue']}")
            print(f"COMPLETED_COUNT={completed}")
            print(f"TOTAL_COUNT={total}")
    elif command == "tick":
        kv = _parse_kv_args(sys.argv[3:])
        issue_repo = kv.get("issue-repo", "")
        epic_num = int(kv.get("epic", "0"))
        issues_str = kv.get("issues", "")
        completed = [int(x) for x in issues_str.split(",") if x.strip()]
        if not issue_repo or not epic_num or not completed:
            print("ERROR=missing_args")
            sys.exit(1)
        ok = tick_epic_checkboxes(issue_repo, epic_num, completed)
        print(f"TICK={'ok' if ok else 'failed'}")
    elif command == "write":
        kv = _parse_kv_args(sys.argv[3:])
        workspace = Path(kv.get("workspace", ""))
        issue = kv.get("issue", "")
        slug = kv.get("slug", "")
        issue_repo = kv.get("issue-repo", "")
        context = kv.get("context", "")
        batches_json = kv.get("batches", "[]")
        batches = json.loads(batches_json)
        if not workspace or not issue:
            print("ERROR=missing_args (workspace and issue required)", file=sys.stderr)
            sys.exit(1)
        write_epic(workspace, issue, slug, issue_repo, batches, context)
        print("WRITTEN=yes")
    else:
        print(f"ERROR=unknown_command command={command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
