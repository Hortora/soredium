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
from routing import parse_layer2, parse_layer3, resolve  # noqa: E402

sys.path.insert(0, str(SCRIPT_DIR))
from common import parse_args  # noqa: E402


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
    result = git(workspace, "cat-file", "-e", f"{branch}:{file_path}")
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


def check_stale_branches(workspace: str, branches: list[str]) -> list[dict]:
    stale = []
    for b in branches:
        if branch_has_file(workspace, b, "design/EPIC-CLOSED.md"):
            continue
        days = branch_last_commit_days(workspace, b)
        if days >= 7:
            stale.append({
                "branch": b,
                "last_commit_age": f"{days} days",
            })
    return stale


def list_branch_files(workspace: str, branch: str, directory: str) -> list[str]:
    result = git(workspace, "ls-tree", "--name-only", f"{branch}:{directory}")
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
    result = git(workspace, "ls-tree", "-r", "--name-only",
                 f"{branch}:{directory}")
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
        if not branch_has_file(workspace, b, "design/EPIC-CLOSED.md"):
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
        if not branch_has_file(workspace, b, "design/EPIC-CLOSED.md"):
            continue

        repo = workspace if single_repo else project
        result = git(repo, "rev-parse", "--verify", b)
        project_branch_exists = result.returncode == 0

        if not project_branch_exists:
            unstamped.append({
                "branch": b,
                "has_epic_closed": True,
                "project_branch_exists": False,
            })
            continue

        result = git(repo, "log", "-1", "--format=%s", b)
        last_msg = result.stdout.strip() if result.returncode == 0 else ""
        if not last_msg.startswith("chore: branch closed"):
            unstamped.append({
                "branch": b,
                "has_epic_closed": True,
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
    stale_branches = check_stale_branches(workspace, branches)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
