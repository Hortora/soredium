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
    ws_status = git(workspace, "status", "--porcelain")
    proj_status = git(project, "status", "--porcelain")

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


def check_meta_exists(workspace: str) -> dict:
    meta_path = Path(workspace) / "design" / ".meta"
    if not meta_path.exists():
        return {"status": "needs_input", "detail": "no-meta"}

    meta_data = {}
    for line in meta_path.read_text().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta_data[k.strip()] = v.strip()

    return {
        "status": "pass",
        "meta": meta_data,
    }


def get_branch(repo: str) -> str:
    result = git(repo, "branch", "--show-current")
    return result.stdout.strip() if result.returncode == 0 else ""


def gather_context(workspace: str, project: str) -> dict:
    preconditions: dict[str, dict] = {}

    preconditions["clean_tree"] = check_clean_tree(workspace, project)
    meta_result = check_meta_exists(workspace)
    preconditions["meta_exists"] = {
        k: v for k, v in meta_result.items() if k != "meta"
    }

    branch = get_branch(workspace)
    meta = meta_result.get("meta", {})

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
