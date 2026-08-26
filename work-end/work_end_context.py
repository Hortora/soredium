#!/usr/bin/env python3
"""
work_end_context.py — Unified context and precondition gathering for work-end.

Absorbs pre-conditions (clean tree, .meta existence, branch state) and
context resolution (workspace, project, branch, routing) into a single
JSON output. The SKILL.md handles interactive resolution for needs_input
conditions; fail conditions are non-interactive hard stops.

Usage:
    python3 work_end_context.py workspace=<path> project=<path>

Output: Single JSON object on stdout.
Exit 0 always (even with fail/needs_input conditions).
Exit 1 only for operational errors (bad args, missing dirs).
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args


def git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
        timeout=10,
    )


def check_clean_tree(workspace: str, project: str) -> dict:
    ws_status = git(workspace, "status", "--porcelain", "--", ".")
    proj_status = git(project, "status", "--porcelain", "--", ".")

    ws_dirty = bool(ws_status.stdout.strip()) if ws_status.returncode == 0 else False
    proj_dirty = bool(proj_status.stdout.strip()) if proj_status.returncode == 0 else False

    if ws_dirty or proj_dirty:
        details = []
        if ws_dirty:
            details.append("workspace has uncommitted changes")
        if proj_dirty:
            details.append("project has uncommitted changes")
        return {"status": "fail", "detail": "; ".join(details)}
    return {"status": "pass"}


def check_meta_exists(workspace: str, current_branch: str = "") -> dict:
    ws = Path(workspace)
    plan_path = ws / ".plan"
    target = plan_path
    if not target.exists():
        return {"status": "needs_input", "detail": "no-meta"}

    meta_data = {}
    in_state = False
    has_sections = False
    for line in target.read_text().splitlines():
        if line.strip() == "## State":
            in_state = True
            has_sections = True
            continue
        if line.startswith("## "):
            in_state = False
            continue
        if has_sections and not in_state:
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            meta_data[k.strip()] = v.strip()

    plan_branch = meta_data.get("branch", "")
    if current_branch and plan_branch and plan_branch != current_branch:
        return {
            "status": "needs_input",
            "detail": "stale-plan",
            "stale_branch": plan_branch,
            "meta": meta_data,
        }

    return {
        "status": "pass",
        "meta": meta_data,
    }


def get_branch(repo: str) -> str:
    result = git(repo, "branch", "--show-current")
    return result.stdout.strip() if result.returncode == 0 else ""


def check_isx_staleness(workspace: str, project: str) -> dict:
    slot_dir = Path(project).parent
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return {"status": "skip"}

    slot_skill = Path(__file__).parent.parent / "work-slot"
    sys.path.insert(0, str(slot_skill))
    try:
        from slot_manager import parse_slot_md, get_slot_repos
    except ImportError:
        return {"status": "skip"}

    info = parse_slot_md(slot_dir)
    if info.get("isolation_type") != "isx":
        return {"status": "skip"}

    stale_repos = []
    for repo_name in get_slot_repos(slot_dir):
        clone_path = slot_dir / repo_name
        if not clone_path.is_dir():
            continue
        local_head = git(str(clone_path), "rev-parse", "HEAD")
        remote = git(str(clone_path), "ls-remote", "isx", "HEAD")
        if local_head.returncode != 0 or remote.returncode != 0:
            continue
        local_sha = local_head.stdout.strip()
        remote_sha = remote.stdout.split()[0] if remote.stdout.strip() else ""
        if remote_sha and local_sha != remote_sha:
            stale_repos.append(repo_name)

    if stale_repos:
        return {
            "status": "needs_input",
            "detail": "isx-stale",
            "repos": stale_repos,
        }
    return {"status": "pass"}


def check_branch_alignment(workspace: str, project: str) -> dict:
    ws_branch = get_branch(workspace)
    proj_branch = get_branch(project)
    if not ws_branch or not proj_branch:
        return {"status": "fail", "detail": "cannot determine branch"}
    if ws_branch == "main" and proj_branch != "main":
        return {"status": "fail", "detail": f"workspace on main but project on {proj_branch} — workspace branch missing"}
    if ws_branch != proj_branch:
        return {"status": "fail", "detail": f"workspace on {ws_branch}, project on {proj_branch} — branch mismatch"}
    return {"status": "pass"}


def gather_context(workspace: str, project: str) -> dict:
    _slot_dir = str(Path(__file__).parent.parent / "work-slot")
    if _slot_dir not in sys.path:
        sys.path.insert(0, _slot_dir)
    from plan_migrate import migrate_to_root
    migrate_to_root(Path(workspace))

    preconditions: dict[str, dict] = {}

    preconditions["branch_alignment"] = check_branch_alignment(workspace, project)
    preconditions["clean_tree"] = check_clean_tree(workspace, project)
    preconditions["isx_staleness"] = check_isx_staleness(workspace, project)
    current_branch = get_branch(workspace)
    meta_result = check_meta_exists(workspace, current_branch=current_branch)
    preconditions["meta_exists"] = {
        k: v for k, v in meta_result.items() if k != "meta"
    }

    branch = current_branch
    meta = meta_result.get("meta", {})

    if meta_result.get("detail") == "stale-plan":
        meta = {}

    context = {
        "workspace": workspace,
        "project": project,
        "branch": branch,
        "issue": meta.get("issue", ""),
        "issue_repo": meta.get("issue-repo", ""),
        "covers": meta.get("covers", ""),
        "project_sha": meta.get("project-sha", ""),
        "design_repo": meta.get("design-repo", ""),
        "state": meta.get("state", ""),
    }

    if not context["issue"] and branch:
        import re
        m = re.search(r'issue-(\d+)', branch)
        if m:
            context["issue"] = m.group(1)

    return {
        "preconditions": preconditions,
        "context": context,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: work_end_context.py workspace=<path> project=<path>",
              file=sys.stderr)
        return 1

    opts = parse_args(sys.argv[1:])
    workspace = opts.get("workspace", "")
    project = opts.get("project", "")

    if not workspace or not project:
        print("ERROR=MISSING_ARGS", file=sys.stderr)
        print("ERROR_DETAIL=workspace= and project= are required", file=sys.stderr)
        return 1

    if not Path(workspace).is_dir():
        print(f"ERROR=BAD_PATH workspace={workspace} not found", file=sys.stderr)
        return 1
    if not Path(project).is_dir():
        print(f"ERROR=BAD_PATH project={project} not found", file=sys.stderr)
        return 1

    result = gather_context(workspace, project)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
