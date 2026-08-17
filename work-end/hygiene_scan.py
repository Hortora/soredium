#!/usr/bin/env python3
"""
Hygiene scan for work-end — replaces the Step 8i subagent dispatch.

Scans workspace branches for hygiene issues: unpublished blogs, flyway
conflicts, stale branches, unrecovered artifacts, unstamped branches.
All checks are mechanical (git commands, file existence) — no LLM needed.

Usage:
    python3 hygiene_scan.py <workspace> <project> \
      branch=<name> blog_dest=<path> flyway_used=<yes|no> \
      single_repo=<yes|no>

Output: JSON object matching the subagent contract (stdout).
Errors: printed to stderr, exit code 1.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_ROOT = SCRIPT_DIR.parent
ROUTING_DIR = SKILL_ROOT / "project"

sys.path.insert(0, str(ROUTING_DIR))
from lifecycle import ClosureState, is_closed  # noqa: E402
from routing import parse_layer2, parse_layer3, resolve  # noqa: E402

sys.path.insert(0, str(SCRIPT_DIR))
from common import parse_args, subdir_prefix  # noqa: E402


def git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
    )


def check_unpublished_blogs(workspace: str, blog_dest: str) -> list[str]:
    blog_dir = Path(workspace) / "blog"
    if not blog_dir.is_dir() or not blog_dest:
        return []

    dest_path = Path(blog_dest).expanduser()
    unpublished = []
    for f in blog_dir.iterdir():
        if f.name == "INDEX.md" or not f.name.endswith(".md"):
            continue
        if not (dest_path / f.name).exists():
            unpublished.append(f.name)
    return sorted(unpublished)


def list_workspace_branches(workspace: str, skip_branch: str) -> list[str]:
    result = git(workspace, "branch", "--format=%(refname:short)")
    if result.returncode != 0:
        return []
    branches = []
    for line in result.stdout.strip().split("\n"):
        b = line.strip()
        if b and b != "main" and b != skip_branch:
            branches.append(b)
    return branches


def branch_has_file(workspace: str, branch: str, file_path: str) -> bool:
    prefix = subdir_prefix(workspace)
    result = git(workspace, "cat-file", "-e", f"{branch}:{prefix}{file_path}")
    return result.returncode == 0


def branch_last_commit_days(workspace: str, branch: str) -> int:
    result = git(workspace, "log", "-1", "--format=%ci", branch)
    if result.returncode != 0 or not result.stdout.strip():
        return -1
    try:
        commit_date = datetime.fromisoformat(result.stdout.strip())
        now = datetime.now(timezone.utc)
        if commit_date.tzinfo is None:
            commit_date = commit_date.replace(tzinfo=timezone.utc)
        return (now - commit_date).days
    except (ValueError, TypeError):
        return -1


def check_stale_branches(workspace: str, branches: list[str],
                         project: str | None = None) -> list[dict]:
    stale = []
    for b in branches:
        repo = project or workspace
        state = is_closed(repo, b, workspace=workspace)
        if state in (ClosureState.CLOSED, ClosureState.DELETED):
            continue
        days = branch_last_commit_days(workspace, b)
        if days >= 7:
            stale.append({
                "branch": b,
                "last_commit_age": f"{days} days",
            })
    return stale


def list_branch_files(workspace: str, branch: str, directory: str) -> list[str]:
    prefix = subdir_prefix(workspace)
    result = git(workspace, "ls-tree", "--full-tree", "--name-only",
                 f"{branch}:{prefix}{directory}")
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().split("\n") if f]


def list_project_files(project: str, directory: str) -> list[str]:
    path = Path(project) / directory
    if not path.is_dir():
        return []
    return [f.name for f in path.iterdir() if f.is_file()]


def list_branch_files_recursive(workspace: str, branch: str,
                                directory: str) -> list[str]:
    prefix = subdir_prefix(workspace)
    result = git(workspace, "ls-tree", "--full-tree", "-r", "--name-only",
                 f"{branch}:{prefix}{directory}")
    if result.returncode != 0:
        return []
    files = []
    for line in result.stdout.strip().split("\n"):
        name = line.strip()
        if not name:
            continue
        files.append(name.rsplit("/", 1)[-1] if "/" in name else name)
    return files


def check_unrecovered_artifacts(workspace: str, project: str,
                                branches: list[str],
                                routing: dict[str, str]) -> list[dict]:
    unrecovered = []
    for b in branches:
        ws_state = is_closed(workspace, b)
        if ws_state not in (ClosureState.CLOSED, ClosureState.MERGED_UNSTAMPED,
                            ClosureState.STAMPED_UNMERGED):
            continue

        for artifact_type, ws_directory in [("blog", "blog"), ("specs", "specs")]:
            dest = routing.get(artifact_type, "project")
            if dest == "project":
                branch_files = list_branch_files_recursive(
                    workspace, b, ws_directory)
                promoted_files = list_project_files(
                    project, f"docs/{ws_directory}")
            else:
                branch_files = list_branch_files(workspace, b, ws_directory)
                promoted_files = list_branch_files(
                    workspace, "main", ws_directory)
            for f in branch_files:
                if f == "INDEX.md":
                    continue
                if f not in promoted_files:
                    unrecovered.append({
                        "branch": b,
                        "type": artifact_type,
                        "file": f,
                    })
    return unrecovered


def check_unstamped_branches(workspace: str, project: str,
                              branches: list[str], single_repo: bool) -> list[dict]:
    unstamped = []
    for b in branches:
        repo = project if not single_repo else workspace
        state = is_closed(repo, b, workspace=workspace)
        if state == ClosureState.MERGED_UNSTAMPED:
            unstamped.append({
                "branch": b,
                "closure_state": state.value,
                "project_branch_exists": True,
            })
        elif state == ClosureState.STAMPED_UNMERGED:
            unstamped.append({
                "branch": b,
                "closure_state": state.value,
                "project_branch_exists": True,
            })
    return unstamped


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: hygiene_scan.py <workspace> <project> key=value ...", file=sys.stderr)
        return 1

    workspace = sys.argv[1]
    project = sys.argv[2]
    opts = parse_args(sys.argv[3:])

    branch = opts.get("branch", "")
    blog_dest = opts.get("blog_dest", "")
    flyway_used = opts.get("flyway_used", "no")
    single_repo = opts.get("single_repo", "no") == "yes"

    if not branch:
        print("ERROR: branch= is required", file=sys.stderr)
        return 1

    global_md = Path.home() / ".claude" / "CLAUDE.md"
    workspace_md = Path(workspace) / "CLAUDE.md"
    global_text = global_md.read_text() if global_md.exists() else ""
    workspace_text = workspace_md.read_text() if workspace_md.exists() else ""
    layer2 = parse_layer2(global_text)
    layer3 = parse_layer3(workspace_text)
    routing = {a: resolve(a, layer2, layer3)[0] for a in ("blog", "specs")}

    branches = list_workspace_branches(workspace, branch)

    unpublished_blogs = check_unpublished_blogs(workspace, blog_dest)
    stale_branches = check_stale_branches(workspace, branches, project=project)
    unrecovered = check_unrecovered_artifacts(workspace, project, branches, routing)
    unstamped = check_unstamped_branches(workspace, project, branches, single_repo)

    # Flyway conflict detection is a placeholder — the actual V-number
    # collision logic depends on migration file naming conventions that
    # vary per project. Step 2 already handles this at close time.
    flyway_conflicts: list[str] = []

    result = {
        "unpublished_blogs": unpublished_blogs,
        "flyway_conflicts": flyway_conflicts,
        "stale_branches": stale_branches,
        "unrecovered_artifacts": unrecovered,
        "unstamped_branches": unstamped,
    }

    json.dump(result, sys.stdout, indent=2)
    print()

    persist_findings(workspace, result)
    return 0


def persist_findings(workspace: str, result: dict) -> None:
    audit_dir = Path(workspace) / ".audit"
    audit_dir.mkdir(exist_ok=True)
    findings_path = audit_dir / "findings.json"
    stamp = datetime.now(timezone.utc).isoformat()
    findings = []
    for entry in result.get("unrecovered_artifacts", []):
        findings.append({
            "category": "hygiene",
            "check": "unrecovered_artifact",
            "detail": f"{entry['type']} {entry['file']} on closed branch {entry['branch']}",
            "status": "open",
            "timestamp": stamp,
        })
    for entry in result.get("unstamped_branches", []):
        findings.append({
            "category": "hygiene",
            "check": "unstamped_branch",
            "detail": f"{entry['branch']} is {entry['closure_state']}",
            "status": "open",
            "timestamp": stamp,
        })
    for entry in result.get("stale_branches", []):
        findings.append({
            "category": "hygiene",
            "check": "stale_branch",
            "detail": f"{entry['branch']} — last commit {entry['last_commit_age']} ago",
            "status": "open",
            "timestamp": stamp,
        })
    if findings:
        existing = []
        if findings_path.exists():
            try:
                existing = json.loads(findings_path.read_text())
            except (json.JSONDecodeError, ValueError):
                existing = []
        existing_keys = {(f["check"], f["detail"]) for f in existing if f.get("status") == "open"}
        for f in findings:
            if (f["check"], f["detail"]) not in existing_keys:
                existing.append(f)
        findings_path.write_text(json.dumps(existing, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
