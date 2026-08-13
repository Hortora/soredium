#!/usr/bin/env python3
"""
brief.py — Structured orientation data for the current work state.

Composes ctx.resolve(), work_router.detect_state(), work_health.run_checks(),
and HANDOFF.md parsing into a unified KEY=VALUE output consumable by the
/brief skill and the future Trellis frame.

Usage:
    python3 brief.py [--cwd <path>]

Output format: see spec D5 in work-command-taxonomy-design.md
"""
import io
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
_PROJECT_DIR = _SCRIPT_DIR.parent / "project"

if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from ctx import resolve as ctx_resolve
from work_health import run_checks
from lifecycle import is_closed, ClosureState


def _extract_handoff_summary(handoff_path: str) -> str:
    """Extract the first 2-3 lines of the Last Session section from HANDOFF.md."""
    path = Path(handoff_path)
    if not path.exists():
        return ""
    content = path.read_text()

    in_section = False
    lines = []
    for line in content.splitlines():
        if re.match(r"^##\s+Last Session", line):
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
            if len(lines) >= 3:
                break
    return " ".join(lines)


def _recent_commits(project: str, base_branch: str = "main", max_count: int = 6) -> list[str]:
    """Get recent commits on the current branch since base."""
    result = subprocess.run(
        ["git", "-C", project, "log", "--oneline",
         f"{base_branch}..HEAD", f"-{max_count}"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []
    return [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]


def _closed_branches(project: str, workspace: str | None, max_count: int = 5) -> list[dict]:
    """Enumerate recently closed branches (for main_idle state)."""
    result = subprocess.run(
        ["git", "-C", project, "for-each-ref",
         "--sort=-committerdate", "--format=%(refname:short)",
         "refs/heads/issue-*"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []

    candidates = result.stdout.strip().splitlines()[:10]
    closed = []
    for branch in candidates:
        state = is_closed(project, branch, workspace)
        if state in (ClosureState.CLOSED, ClosureState.MERGED_UNSTAMPED):
            issue_match = re.match(r"issue-(\d+)", branch)
            issue_n = issue_match.group(1) if issue_match else ""

            age_result = subprocess.run(
                ["git", "-C", project, "log", "-1",
                 "--format=%cr", branch],
                capture_output=True, text=True, timeout=10,
            )
            age = age_result.stdout.strip() if age_result.returncode == 0 else ""
            closed.append({"branch": branch, "issue": issue_n, "closed": age})
            if len(closed) >= max_count:
                break
    return closed


def _capture_health(scope: str, project: str, workspace: str,
                    owner_repo: str | None = None) -> list[str]:
    """Run work_health.run_checks and capture its printed output."""
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            run_checks(scope, project, workspace, owner_repo=owner_repo)
    except Exception:
        pass
    return [l for l in buf.getvalue().strip().splitlines() if l.strip()]


def resolve(cwd: str | None = None) -> dict:
    """Resolve structured orientation data. Returns a dict with scalar fields
    and list fields (commits, checks, closed_branches)."""
    ctx = ctx_resolve(cwd=cwd)
    project = ctx.get("PROJECT", "")
    workspace = ctx.get("WORKSPACE", project)
    current_branch = ctx.get("CURRENT_BRANCH", "")
    owner_repo = ctx.get("OWNER_REPO", "")
    base_branch = ctx.get("BASE_BRANCH", "main")

    on_main = ctx.get("ON_MAIN") == "yes"
    stack_depth = int(ctx.get("STACK_DEPTH", "0"))
    has_plan = ctx.get("HAS_PLAN", "no")
    has_handoff = ctx.get("HAS_HANDOFF", "no")
    handoff_path = ctx.get("HANDOFF_PATH", "")
    issue = ctx.get("ISSUE_N", "")

    if on_main:
        state = "main_with_stack" if stack_depth > 0 else "main_idle"
    else:
        state = "feature_branch"

    result = {
        "STATE": state,
        "BRANCH": current_branch if not on_main else "",
        "ISSUE": issue,
        "STACK_DEPTH": str(stack_depth),
        "HAS_PLAN": has_plan,
        "HAS_HANDOFF": has_handoff,
    }

    if has_plan == "yes":
        result["PLAN_POSITION"] = ctx.get("PLAN_POSITION", "")
        result["PLAN_ACTIVE_ISSUE"] = ctx.get("PLAN_ACTIVE_ISSUE", "")
        result["PLAN_BATCH"] = ctx.get("PLAN_BATCH", "")

    handoff_summary = ""
    if handoff_path:
        handoff_summary = _extract_handoff_summary(handoff_path)
    result["HANDOFF_SUMMARY"] = handoff_summary

    commits = []
    if state == "feature_branch":
        commits = _recent_commits(project, base_branch)
    result["RECENT_COMMITS"] = str(len(commits))
    result["_commits"] = commits

    health_lines = []
    if state == "feature_branch":
        health_lines = _capture_health(
            "entry", project, workspace,
            owner_repo=owner_repo if owner_repo else None,
        )
    result["_checks"] = [l for l in health_lines
                         if l.startswith("CHECK=") or "STATUS=" in l]

    closed = []
    if state == "main_idle":
        closed = _closed_branches(project, workspace)
    result["_closed_branches"] = closed

    return result


def _print_output(data: dict) -> None:
    """Print structured KEY=VALUE output."""
    skip_internal = {"_commits", "_checks", "_closed_branches"}
    for key, value in data.items():
        if key in skip_internal:
            continue
        print(f"{key}={value}")

    for commit in data.get("_commits", []):
        print(f"COMMIT={commit}")

    for check_line in data.get("_checks", []):
        if not check_line.startswith("CHECK="):
            check_line = f"CHECK={check_line}"
        print(check_line)

    for closed in data.get("_closed_branches", []):
        print(f"CLOSED_BRANCH={closed['branch']} ISSUE={closed['issue']} CLOSED={closed['closed']}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Work orientation data")
    parser.add_argument("--cwd", default=None, help="Working directory override")
    args = parser.parse_args()

    try:
        data = resolve(cwd=args.cwd)
        _print_output(data)
        return 0
    except Exception as e:
        print(f"ERROR={e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
