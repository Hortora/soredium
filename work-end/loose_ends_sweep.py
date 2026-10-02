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


ISSUE_REF_PATTERN = re.compile(
    r"(?:Refs|Closes|Fixes|refs|closes|fixes)?\s*#(\d+)"
    r"|(?:\(#(\d+)\))"
)


def _extract_issue_refs(message: str) -> set[int]:
    """Extract issue numbers from a commit message."""
    refs: set[int] = set()
    for m in ISSUE_REF_PATTERN.finditer(message):
        num = m.group(1) or m.group(2)
        if num:
            refs.add(int(num))
    return refs


def scan_commit_coverage(project: str, branch: str, covers: str,
                         base: str = "main") -> list[dict]:
    """Flag commits referencing issues not in the covers list."""
    if not project or not branch or not covers:
        return []
    covers_set = {int(c.strip()) for c in covers.split(",") if c.strip().isdigit()}
    if not covers_set:
        return []

    try:
        result = subprocess.run(
            ["git", "-C", project, "log", "--format=%H %s", f"{base}..{branch}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, OSError):
        return []

    findings: list[dict] = []
    stamp = datetime.now(timezone.utc).isoformat()

    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        sha, subject = parts[0], parts[1]
        if subject.startswith("chore: branch closed") or subject.startswith("chore: commit lifecycle"):
            continue
        refs = _extract_issue_refs(subject)
        orphaned = refs - covers_set
        for issue_num in sorted(orphaned):
            findings.append({
                "category": "loose-end",
                "check": "commit-outside-covers",
                "location": f"{sha[:8]}",
                "detail": f"Commit {sha[:8]} references #{issue_num} (not in covers: {covers}): {subject[:120]}",
                "severity": "warning",
                "source": "loose-ends-sweep",
                "branch": branch,
                "status": "open",
                "timestamp": stamp,
                "issue_num": issue_num,
            })

    return findings


def _classify_file(path: str) -> str:
    """Classify a file as src, test, or config."""
    lower = path.lower()
    if "test" in lower or "spec" in lower:
        return "test"
    if any(lower.endswith(ext) for ext in (
        ".yaml", ".yml", ".json", ".toml", ".xml", ".properties",
        ".cfg", ".ini", ".env",
    )):
        return "config"
    return "src"


def _find_introducing_commit(project: str, filepath: str,
                              base: str, branch: str) -> tuple[str, str]:
    """Find the commit that introduced a file on the branch."""
    try:
        result = subprocess.run(
            ["git", "-C", project, "log", "--diff-filter=A",
             "--format=%H %s", f"{base}..{branch}", "--", filepath],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().splitlines()[0]
            parts = line.split(" ", 1)
            return parts[0][:8], parts[1] if len(parts) > 1 else ""
    except (subprocess.TimeoutExpired, OSError):
        pass
    return "", ""


def scan_orphaned_content(project: str, branch: str,
                          base: str = "main") -> list[dict]:
    """Flag files added on branch that don't exist on main."""
    if not project or not branch:
        return []

    try:
        result = subprocess.run(
            ["git", "-C", project, "diff", "--diff-filter=A",
             "--name-only", f"{base}..{branch}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, OSError):
        return []

    added_files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    if not added_files:
        return []

    orphaned: list[str] = []
    for filepath in added_files:
        check = subprocess.run(
            ["git", "-C", project, "cat-file", "-e", f"{base}:{filepath}"],
            capture_output=True, text=True, timeout=5,
        )
        if check.returncode != 0:
            orphaned.append(filepath)

    if not orphaned:
        return []

    findings: list[dict] = []
    stamp = datetime.now(timezone.utc).isoformat()

    for filepath in orphaned:
        sha, subject = _find_introducing_commit(project, filepath, base, branch)
        issue_refs = _extract_issue_refs(subject) if subject else set()
        findings.append({
            "category": "loose-end",
            "check": "orphaned-content",
            "location": filepath,
            "detail": (f"File added on branch but not on {base}"
                       + (f" (introduced by {sha}: {subject[:80]})" if sha else "")),
            "severity": "warning",
            "source": "loose-ends-sweep",
            "branch": branch,
            "status": "open",
            "timestamp": stamp,
            "file_type": _classify_file(filepath),
            "introducing_commit": sha,
            "issue_refs": sorted(issue_refs) if issue_refs else [],
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
    covers = args.get("covers", "")
    base_branch = args.get("base_branch", "main")
    cycle_start = args.get("cycle_start")

    if not workspace or not branch:
        print("ERROR=missing workspace or branch", file=sys.stderr)
        return 1

    new_findings: list[dict] = []
    new_findings.extend(scan_deferred_plan_items(workspace, branch))

    if project:
        new_findings.extend(scan_todos(project, branch))
        new_findings.extend(scan_orphaned_content(project, branch, base=base_branch))
        new_findings.extend(scan_commit_coverage(project, branch, covers, base=base_branch))

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
