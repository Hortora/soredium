#!/usr/bin/env python3
"""
Epic context propagation for HANDOFF.md (#487).

When work-end closes an issue that belongs to an epic, this module
writes HANDOFF.md with the epic's status table and recommended next
issue. Without this, the next session starts cold with a stale HANDOFF.

Detection order:
1. .plan queue structure (plan_manager's epic/child hierarchy)
2. GitHub issue body ("Parent epic: #N", "(parent)", "Part of #N")
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_slot_dir = str(Path(__file__).resolve().parent.parent / "work-slot")
if _slot_dir not in sys.path:
    sys.path.insert(0, _slot_dir)
_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)


# ---------------------------------------------------------------------------
# Epic detection — from .plan
# ---------------------------------------------------------------------------

def detect_parent_epic_from_plan(issue_number: int, plan_path: Path):
    """Find the parent epic of an issue via .plan queue structure.

    Returns an IssueRef or None.
    """
    if not plan_path.exists():
        return None
    try:
        from plan_manager import parse_plan, flatten_leaves
        tree = parse_plan(plan_path)
        leaves = flatten_leaves(tree)
        for leaf in leaves:
            if leaf.ref and leaf.ref.number == issue_number:
                return leaf.parent_epic
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Epic detection — from GitHub issue body
# ---------------------------------------------------------------------------

_PARENT_PATTERNS = [
    re.compile(r'(?:Parent epic|parent epic):\s*#(\d+)', re.IGNORECASE),
    re.compile(r'Part of\s+#(\d+)', re.IGNORECASE),
    re.compile(r'#(\d+)\s*[—–-]\s*.*?\(parent\)', re.IGNORECASE),
]


def detect_parent_epic_from_body(body: str) -> int | None:
    """Parse a GitHub issue body for parent epic references."""
    if not body:
        return None
    for pattern in _PARENT_PATTERNS:
        match = pattern.search(body)
        if match:
            return int(match.group(1))
    return None


def _fetch_issue(issue_number: int, repo: str) -> dict | None:
    """Fetch issue title and body from GitHub."""
    try:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_number), "--repo", repo,
             "--json", "title,body"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return None


# ---------------------------------------------------------------------------
# Epic children parsing
# ---------------------------------------------------------------------------

_CHILD_RE = re.compile(
    r'^\s*-\s+\[([ xX])\]\s+#(\d+)\s*[—–-]\s*(.+?)(?:\s*\(.*?\))?(?:[ \t]*[—–-][ \t]*[^\n]*)?$',
    re.MULTILINE,
)


def parse_epic_children(body: str) -> list[dict]:
    """Parse an epic issue body for child issues and their statuses."""
    children = []
    for match in _CHILD_RE.finditer(body):
        done = match.group(1).lower() == 'x'
        number = int(match.group(2))
        title = match.group(3).strip()
        children.append({"number": number, "title": title, "done": done})
    return children


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

def recommend_next(children: list[dict]) -> dict | None:
    """Return the first open child issue as the recommended next."""
    for child in children:
        if not child["done"]:
            return child
    return None


# ---------------------------------------------------------------------------
# HANDOFF content
# ---------------------------------------------------------------------------

def build_epic_handoff(
    completed_issue: int,
    completed_title: str,
    epic_number: int,
    epic_title: str,
    children: list[dict],
    repo: str,
    branch: str,
) -> str:
    """Build structured HANDOFF.md content with epic context."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    done_count = sum(1 for c in children if c["done"])
    total = len(children)

    lines = [
        "# Handoff",
        "",
        "## Session Summary",
        f"",
        f"Completed **#{completed_issue}** — {completed_title}",
        f"Branch: `{branch}`",
        f"Date: {ts}",
        "",
        f"## Epic Status: #{epic_number} — {epic_title}",
        "",
        f"Progress: {done_count}/{total}",
        "",
        "| # | Title | Status |",
        "|---|-------|--------|",
    ]

    for child in children:
        status = "✅ Done" if child["done"] else "🔲 Open"
        lines.append(f"| #{child['number']} | {child['title']} | {status} |")

    lines.append("")

    next_issue = recommend_next(children)
    if next_issue:
        lines.append("### Recommended Next")
        lines.append("")
        lines.append(f"**#{next_issue['number']}** — {next_issue['title']}")
        lines.append("")
    elif done_count == total and total > 0:
        lines.append("### Epic Complete ✅")
        lines.append("")
        lines.append(f"All {total} issues in #{epic_number} are done.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def write_epic_handoff(
    workspace: Path,
    completed_issue: int,
    completed_title: str,
    epic_number: int,
    epic_title: str,
    children: list[dict],
    repo: str,
    branch: str,
) -> None:
    """Write HANDOFF.md to workspace with epic context."""
    content = build_epic_handoff(
        completed_issue=completed_issue,
        completed_title=completed_title,
        epic_number=epic_number,
        epic_title=epic_title,
        children=children,
        repo=repo,
        branch=branch,
    )
    (workspace / "HANDOFF.md").write_text(content)


# ---------------------------------------------------------------------------
# Orchestrator entry point
# ---------------------------------------------------------------------------

def run_epic_handoff(
    workspace: Path,
    covers: str,
    issue_repo: str,
    plan_path: Path | None,
    branch: str,
) -> dict[str, str]:
    """Detect epic context and write HANDOFF.md.

    Called as a mechanical step in the work-end pipeline.
    Returns KEY=VALUE dict for orchestrator output.
    """
    if not covers or not issue_repo:
        return {"EPIC_HANDOFF": "skipped", "REASON": "no_covers"}

    from plan_io import parse_covers_qualified
    refs = parse_covers_qualified(covers)
    if not refs:
        return {"EPIC_HANDOFF": "skipped", "REASON": "no_refs"}

    first_ref = refs[0]
    issue_number = first_ref.number
    issue_repo_resolved = first_ref.repo or issue_repo

    # 1. Try .plan for epic detection
    epic_number = None
    if plan_path and plan_path.exists():
        epic_ref = detect_parent_epic_from_plan(issue_number, plan_path)
        if epic_ref:
            epic_number = epic_ref.number

    # 2. Fall back to GitHub issue body
    completed_title = ""
    if epic_number is None:
        issue_data = _fetch_issue(issue_number, issue_repo_resolved)
        if issue_data:
            completed_title = issue_data.get("title", "")
            epic_number = detect_parent_epic_from_body(issue_data.get("body", ""))

    if epic_number is None:
        return {"EPIC_HANDOFF": "skipped", "REASON": "no_epic"}

    # 3. Fetch epic details
    epic_data = _fetch_issue(epic_number, issue_repo_resolved)
    if not epic_data:
        return {"EPIC_HANDOFF": "skipped", "REASON": "epic_fetch_failed"}

    epic_title = epic_data.get("title", f"Epic #{epic_number}")
    children = parse_epic_children(epic_data.get("body", ""))

    if not children:
        return {"EPIC_HANDOFF": "skipped", "REASON": "no_children"}

    # Get completed issue title if not already fetched
    if not completed_title:
        child_match = next((c for c in children if c["number"] == issue_number), None)
        if child_match:
            completed_title = child_match["title"]
        else:
            issue_data = _fetch_issue(issue_number, issue_repo_resolved)
            completed_title = issue_data.get("title", f"Issue #{issue_number}") if issue_data else f"Issue #{issue_number}"

    # 4. Write HANDOFF.md
    write_epic_handoff(
        workspace=workspace,
        completed_issue=issue_number,
        completed_title=completed_title,
        epic_number=epic_number,
        epic_title=epic_title,
        children=children,
        repo=issue_repo_resolved,
        branch=branch,
    )

    next_issue = recommend_next(children)
    result: dict[str, str] = {
        "EPIC_HANDOFF": "written",
        "EPIC": str(epic_number),
        "CHILDREN": str(len(children)),
        "DONE": str(sum(1 for c in children if c["done"])),
    }
    if next_issue:
        result["NEXT_ISSUE"] = str(next_issue["number"])
        result["NEXT_TITLE"] = next_issue["title"]
    return result


def main() -> int:
    """CLI entry point for orchestrator script calls."""
    args: dict[str, str] = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            args[k] = v

    workspace = Path(args.get("workspace", ""))
    covers = args.get("covers", "")
    issue_repo = args.get("issue_repo", "")
    plan_path = Path(args["plan_path"]) if args.get("plan_path") else None
    branch = args.get("branch", "")

    result = run_epic_handoff(
        workspace=workspace,
        covers=covers,
        issue_repo=issue_repo,
        plan_path=plan_path,
        branch=branch,
    )

    for k, v in result.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
