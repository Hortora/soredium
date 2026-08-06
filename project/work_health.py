#!/usr/bin/env python3
"""Unified work state validation.

Single check registry replacing scattered validation across handover
epic hygiene, resume cross-check, ARC42 stale scan, verify_slot_close.py,
and audit_slot_merges.py.

Usage:
    python3 project/work_health.py --scope entry --project P --workspace W
    python3 project/work_health.py --scope wrap  --project P --workspace W
    python3 project/work_health.py --scope close --project P --workspace W --branch B
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lifecycle import is_closed, ClosureState


def _git(repo, *args, timeout=10):
    try:
        result = subprocess.run(
            ["git", "-C", str(repo)] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", 1


def _parse_pause_stack(workspace):
    stack_path = Path(workspace) / "design" / ".pause-stack"
    if not stack_path.exists():
        return []
    entries = []
    current = {}
    for line in stack_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("- branch:"):
            if current:
                entries.append(current)
            current = {"branch": line.split(":", 1)[1].strip()}
        elif ":" in line and current:
            key, val = line.split(":", 1)
            current[key.strip()] = val.strip()
    if current:
        entries.append(current)
    return entries


def _parse_yaml_intent(path):
    if not path.exists():
        return None
    try:
        data = {}
        for line in path.read_text().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                data[key.strip()] = val.strip()
        return data
    except Exception:
        return {"_parse_error": True}


def check_meta_consistency(project, workspace):
    meta_path = Path(workspace) / "design" / ".meta"
    if not meta_path.exists():
        return "CHECK=meta_consistency STATUS=ok"
    meta_branch = None
    for line in meta_path.read_text().splitlines():
        if line.startswith("branch:"):
            meta_branch = line.split(":", 1)[1].strip()
            break
    if not meta_branch:
        return "CHECK=meta_consistency STATUS=ok"
    current, _ = _git(workspace, "branch", "--show-current")
    if current == "main" and meta_branch != "main":
        return (f"CHECK=meta_consistency STATUS=warn "
                f"DETAIL=.meta says branch '{meta_branch}' but on main — orphaned .meta")
    if current != meta_branch:
        return (f"CHECK=meta_consistency STATUS=warn "
                f"DETAIL=.meta says '{meta_branch}', git says '{current}'")
    return "CHECK=meta_consistency STATUS=ok"


def check_pause_stack(project, workspace):
    entries = _parse_pause_stack(workspace)
    if not entries:
        return "CHECK=pause_stack STATUS=ok"
    warnings = []
    for e in entries:
        branch = e.get("branch", "unknown")
        exists_out, _ = _git(project, "branch", "--list", branch)
        if not exists_out:
            warnings.append(f"{branch} branch deleted")
    if warnings:
        return f"CHECK=pause_stack STATUS=warn DETAIL={'; '.join(warnings)}"
    return "CHECK=pause_stack STATUS=ok"


def check_workspace_alignment(project, workspace):
    if str(Path(project).resolve()) == str(Path(workspace).resolve()):
        return "CHECK=workspace_alignment STATUS=ok"
    w_branch, _ = _git(workspace, "branch", "--show-current")
    p_branch, _ = _git(project, "branch", "--show-current")
    if w_branch != p_branch:
        return (f"CHECK=workspace_alignment STATUS=warn "
                f"DETAIL=workspace on '{w_branch}', project on '{p_branch}'")
    return "CHECK=workspace_alignment STATUS=ok"


def check_main_divergence(project, workspace):
    warnings = []
    for label, repo in [("project", project), ("workspace", workspace)]:
        ahead, rc = _git(repo, "log", "origin/main..main", "--oneline")
        if rc != 0:
            continue
        if ahead:
            count = len(ahead.splitlines())
            warnings.append(f"{label} {count} commit(s) ahead of origin/main")
        behind, rc = _git(repo, "log", "main..origin/main", "--oneline")
        if rc == 0 and behind:
            count = len(behind.splitlines())
            warnings.append(f"{label} {count} commit(s) behind origin/main")
    if warnings:
        return f"CHECK=main_divergence STATUS=warn DETAIL={'; '.join(warnings)}"
    return "CHECK=main_divergence STATUS=ok"


def check_dirty_main(project, workspace):
    current, _ = _git(project, "branch", "--show-current")
    if current != "main":
        return "CHECK=dirty_main STATUS=ok"
    status, _ = _git(project, "status", "--porcelain")
    if status:
        return "CHECK=dirty_main STATUS=warn DETAIL=project main has uncommitted changes"
    return "CHECK=dirty_main STATUS=ok"


def check_partial_pause(workspace):
    path = Path(workspace) / "design" / ".pausing"
    data = _parse_yaml_intent(path)
    if data is None:
        return "CHECK=partial_pause STATUS=ok"
    branch = data.get("branch", "unknown")
    steps = [f"{k}={v}" for k, v in data.items()
             if k not in ("branch", "started", "_parse_error")]
    return f"CHECK=partial_pause STATUS=warn DETAIL={branch} pause interrupted ({', '.join(steps)})"


def check_partial_resume(workspace):
    path = Path(workspace) / "design" / ".resuming"
    data = _parse_yaml_intent(path)
    if data is None:
        return "CHECK=partial_resume STATUS=ok"
    branch = data.get("branch", "unknown")
    steps = [f"{k}={v}" for k, v in data.items()
             if k not in ("branch", "started", "_parse_error")]
    return f"CHECK=partial_resume STATUS=warn DETAIL={branch} resume interrupted ({', '.join(steps)})"


def check_branch_closure(project, workspace):
    branches_to_check = set()
    for e in _parse_pause_stack(workspace):
        if "branch" in e:
            branches_to_check.add(e["branch"])
    meta_path = Path(workspace) / "design" / ".meta"
    if meta_path.exists():
        for line in meta_path.read_text().splitlines():
            if line.startswith("branch:"):
                branches_to_check.add(line.split(":", 1)[1].strip())
    if not branches_to_check:
        return "CHECK=branch_closure STATUS=ok"
    findings = []
    for branch in sorted(branches_to_check):
        state = is_closed(str(project), branch, workspace=str(workspace))
        if state == ClosureState.MERGED_UNSTAMPED:
            findings.append(f"{branch} MERGED_UNSTAMPED — offer stamp")
        elif state == ClosureState.STAMPED_UNMERGED:
            findings.append(f"{branch} STAMPED_UNMERGED — investigate")
    if findings:
        return f"CHECK=branch_closure STATUS=warn DETAIL={'; '.join(findings)}"
    return "CHECK=branch_closure STATUS=ok"


def check_plan_state(project, workspace, owner_repo=None):
    plan_path = Path(workspace) / "design" / ".plan"
    if not plan_path.exists():
        return "CHECK=plan_state STATUS=ok"
    if not owner_repo:
        return "CHECK=plan_state STATUS=skip DETAIL=no OWNER_REPO configured"

    sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
    from plan_manager import parse_plan, flatten_leaves, mark_completed

    tree = parse_plan(plan_path)
    leaves = flatten_leaves(tree)
    open_issues = [l for l in leaves if not l.completed]
    if not open_issues:
        return "CHECK=plan_state STATUS=ok"

    issue_numbers = [l.issue_number for l in open_issues]

    try:
        result = subprocess.run(
            ["gh", "issue", "list", "--repo", owner_repo, "--state", "all",
             "--json", "number,state,title", "--limit", "500"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return "CHECK=plan_state STATUS=skip DETAIL=GitHub API unavailable"
        import json
        issues = {i["number"]: i for i in json.loads(result.stdout)}
    except (subprocess.TimeoutExpired, Exception):
        return "CHECK=plan_state STATUS=skip DETAIL=GitHub API unavailable"

    changed = []
    unmatched = []
    for num in issue_numbers:
        if num in issues:
            if issues[num]["state"] == "CLOSED":
                mark_completed(plan_path, num)
                changed.append(f"#{num} now CLOSED")
        else:
            unmatched.append(num)

    for num in unmatched:
        try:
            result = subprocess.run(
                ["gh", "issue", "view", str(num), "--repo", owner_repo,
                 "--json", "state", "--jq", ".state"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip() == "CLOSED":
                mark_completed(plan_path, num)
                changed.append(f"#{num} now CLOSED")
        except subprocess.TimeoutExpired:
            pass

    if changed:
        return f"CHECK=plan_state STATUS=changed DETAIL={', '.join(changed)}"
    return "CHECK=plan_state STATUS=ok"


def format_resume_display(workspace, health_output=""):
    """Render .plan as a human-readable queue summary for the resume path."""
    plan_path = Path(workspace) / "design" / ".plan"
    if not plan_path.exists():
        return ""

    sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
    from plan_manager import parse_plan, flatten_leaves

    tree = parse_plan(plan_path)
    leaves = flatten_leaves(tree)
    if not leaves:
        return ""

    completed = [l for l in leaves if l.completed]
    active = [l for l in leaves if l.active]
    pending = [l for l in leaves if not l.completed and not l.active]

    lines = [f"## Queue ({len(leaves)} items, {len(completed)} complete, "
             f"{len(active)} active):"]
    for l in completed:
        lines.append(f"  ✅ #{l.issue_number} — {l.title}")
    for l in active:
        lines.append(f"  → #{l.issue_number} — {l.title} (current)")
    for l in pending:
        lines.append(f"     #{l.issue_number} — {l.title}")

    health_notes = []
    for line in health_output.splitlines():
        if "CHECK=plan_state" in line and "STATUS=changed" in line:
            detail = line.split("DETAIL=", 1)[1] if "DETAIL=" in line else ""
            health_notes.append(f"  work_health: {detail}")
    if health_notes:
        lines.append("")
        lines.extend(health_notes)

    return "\n".join(lines)


ENTRY_CHECKS = [
    lambda p, w: check_meta_consistency(p, w),
    lambda p, w: check_pause_stack(p, w),
    lambda p, w: check_workspace_alignment(p, w),
    lambda p, w: check_main_divergence(p, w),
    lambda p, w: check_dirty_main(p, w),
    lambda p, w: check_partial_pause(w),
    lambda p, w: check_partial_resume(w),
    lambda p, w: check_branch_closure(p, w),
]


def run_checks(scope, project, workspace, branch=None):
    if scope == "entry":
        checks = ENTRY_CHECKS
    else:
        print(f"SCOPE={scope} STATUS=not_implemented")
        return

    fixed = 0
    warnings = 0
    errors = 0

    for check_fn in checks:
        result = check_fn(project, workspace)
        print(result)
        if "STATUS=fix" in result:
            fixed += 1
        elif "STATUS=warn" in result:
            warnings += 1
        elif "STATUS=error" in result:
            errors += 1

    print(f"FIXED={fixed} WARNINGS={warnings} ERRORS={errors}")


def main():
    parser = argparse.ArgumentParser(description="Unified work state validation")
    parser.add_argument("--scope", required=True, choices=["entry", "wrap", "close"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--branch", default=None)
    args = parser.parse_args()
    run_checks(args.scope, args.project, args.workspace, args.branch)


if __name__ == "__main__":
    main()
