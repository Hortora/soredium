#!/usr/bin/env python3
"""Loose ends sweep — captures deferred/skipped/missing items.

Mechanical checks for unfinished work. LLM-dependent checks
(conversation context recall) are handled by the skill SKILL.md.

Usage:
    python3 loose_ends_sweep.py workspace=<WS> project=<PROJ> branch=<BRANCH> [cycle_start=<ISO>]

Output: JSON summary to stdout.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_ROOT = SCRIPT_DIR.parent
PROJECT_DIR = SKILL_ROOT / "project"

sys.path.insert(0, str(PROJECT_DIR))
from findings import read_findings, append_finding


def parse_args(argv: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for arg in argv:
        if "=" in arg:
            key, val = arg.split("=", 1)
            result[key] = val
    return result


def scan_deferred_plan_items(workspace: str, branch: str) -> list[dict]:
    plan_path = Path(workspace) / ".plan"
    if not plan_path.exists():
        return []
    content = plan_path.read_text()
    in_deferred = False
    findings: list[dict] = []
    stamp = datetime.now(timezone.utc).isoformat()
    for line in content.splitlines():
        if line.strip().startswith("## Deferred"):
            in_deferred = True
            continue
        if in_deferred and line.strip().startswith("## "):
            break
        if in_deferred and line.strip().startswith("- [ ]"):
            text = line.strip()[6:].strip()
            issue_match = re.match(r"#(\d+)", text)
            location = f"plan:deferred-{issue_match.group(1)}" if issue_match else f"plan:deferred-item"
            findings.append({
                "category": "loose-end",
                "check": "deferred-plan-item",
                "location": location,
                "detail": text,
                "severity": "warning",
                "source": "loose-ends-sweep",
                "branch": branch,
                "status": "open",
                "timestamp": stamp,
            })
    return findings


def scan_todos(project: str, branch: str) -> list[dict]:
    try:
        result = subprocess.run(
            ["git", "-C", project, "diff", "--name-only", "main...HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "-C", project, "diff", "--name-only", "HEAD~5..HEAD"],
                capture_output=True, text=True, timeout=10,
            )
        changed_files = [f for f in result.stdout.strip().splitlines() if f]
    except (subprocess.TimeoutExpired, Exception):
        return []

    findings: list[dict] = []
    stamp = datetime.now(timezone.utc).isoformat()
    todo_pattern = re.compile(r"(TODO|FIXME|HACK|XXX)", re.IGNORECASE)
    branch_issue = re.search(r"issue-(\d+)", branch)
    issue_num = branch_issue.group(1) if branch_issue else None

    for filepath in changed_files:
        full_path = Path(project) / filepath
        if not full_path.exists() or full_path.is_dir():
            continue
        try:
            lines = full_path.read_text().splitlines()
        except (UnicodeDecodeError, PermissionError):
            continue
        for i, line in enumerate(lines, 1):
            if todo_pattern.search(line):
                if issue_num and issue_num not in line:
                    continue
                findings.append({
                    "category": "loose-end",
                    "check": "todo-in-code",
                    "location": f"{filepath}:{i}",
                    "detail": line.strip()[:200],
                    "severity": "note",
                    "source": "loose-ends-sweep",
                    "branch": branch,
                    "status": "open",
                    "timestamp": stamp,
                })
    return findings


def count_prior_open(workspace: str, branch: str, cycle_start: str | None = None) -> int:
    findings_path = Path(workspace) / ".audit" / "findings.jsonl"
    if not findings_path.exists():
        return 0
    all_findings = read_findings(findings_path)
    open_findings = [f for f in all_findings if f.get("status") == "open"]
    if cycle_start:
        open_findings = [
            f for f in open_findings
            if f.get("timestamp", "") < cycle_start
        ]
    return len(open_findings)


def main() -> int:
    args = parse_args(sys.argv[1:])
    workspace = args.get("workspace", "")
    project = args.get("project", "")
    branch = args.get("branch", "")
    cycle_start = args.get("cycle_start")

    if not workspace or not branch:
        print("ERROR=missing workspace or branch", file=sys.stderr)
        return 1

    new_findings: list[dict] = []
    new_findings.extend(scan_deferred_plan_items(workspace, branch))

    if project:
        new_findings.extend(scan_todos(project, branch))

    prior_open = count_prior_open(workspace, branch, cycle_start)

    findings_path = Path(workspace) / ".audit" / "findings.jsonl"
    for finding in new_findings:
        append_finding(findings_path, finding)

    result = {
        "new_findings": len(new_findings),
        "prior_open": prior_open,
        "total_open": prior_open + len(new_findings),
    }
    json.dump(result, sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
