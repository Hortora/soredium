#!/usr/bin/env python3
"""
Promote workspace artifacts to main branch or project repo, close issues.

Usage: python3 artifact_promote.py <subcommand> <args...>

Subcommands:
    to-workspace-main  <workspace> branch=<name> artifacts=<comma-sep-paths>
    to-project         <project> <workspace> artifacts=<comma-sep-paths>
    cleanup-specs      <workspace> branch=<name>
    close-issues       <repo> covers=<comma-sep-issue-numbers>
    archive-plans      <workspace> branch=<name>

Output (KEY=value lines):
    PROMOTED=<count>   (for to-workspace-main, to-project)
    CLEANED=<count>    (for cleanup-specs)
    CLOSED=<count>     (for close-issues)

Error output:
    ERROR=<error_code>
    ERROR_DETAIL=<message>

Exit codes:
    0  success
    1  missing required args, I/O error, or operation failure
"""

import shutil
import subprocess
import sys
from pathlib import Path

from common import parse_args


def git(*cmd: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd] + list(cmd),
        capture_output=True, text=True, check=True,
    )


def to_workspace_main(workspace: str, params: dict[str, str]) -> int:
    branch = params.get("branch", "")
    artifacts_str = params.get("artifacts", "")

    if not branch:
        print("ERROR=missing_branch")
        print("ERROR_DETAIL=branch= argument required")
        return 1
    if not artifacts_str:
        print("ERROR=missing_artifacts")
        print("ERROR_DETAIL=artifacts= argument required")
        return 1

    artifacts = [a.strip() for a in artifacts_str.split(",") if a.strip()]
    if not artifacts:
        print("PROMOTED=0")
        return 0

    ws = Path(workspace)
    if not ws.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Workspace directory not found: {workspace}")
        return 1

    # Checkout main and pull
    try:
        git("checkout", "main", cwd=workspace)
    except subprocess.CalledProcessError as e:
        print("ERROR=checkout_failed")
        print(f"ERROR_DETAIL=Failed to checkout main: {e.stderr.strip()}")
        return 1

    try:
        git("pull", "--rebase", "origin", "main", cwd=workspace)
    except subprocess.CalledProcessError:
        # Pull may fail if no remote — continue
        pass

    # Checkout files from branch
    promoted = 0
    for artifact in artifacts:
        try:
            git("checkout", branch, "--", artifact, cwd=workspace)
            git("add", artifact, cwd=workspace)
            promoted += 1
        except subprocess.CalledProcessError:
            # Skip artifacts that don't exist on the branch
            pass

    if promoted > 0:
        try:
            git("commit", "-m", f"docs(work-end): promote artifacts from {branch}", cwd=workspace)
        except subprocess.CalledProcessError as e:
            # Nothing to commit (already up to date)
            if "nothing to commit" not in e.stdout and "nothing to commit" not in e.stderr:
                print("ERROR=commit_failed")
                print(f"ERROR_DETAIL=Failed to commit: {e.stderr.strip()}")
                return 1

        try:
            git("push", cwd=workspace)
            print("PUSHED=yes")
        except subprocess.CalledProcessError as e:
            print("PUSHED=no")
            print(f"PUSH_ERROR={e.stderr.strip()}")

    # Switch back to branch
    try:
        git("checkout", branch, cwd=workspace)
    except subprocess.CalledProcessError:
        pass

    print(f"PROMOTED={promoted}")
    return 0


def to_project(project: str, workspace: str, params: dict[str, str]) -> int:
    artifacts_str = params.get("artifacts", "")

    if not artifacts_str:
        print("ERROR=missing_artifacts")
        print("ERROR_DETAIL=artifacts= argument required")
        return 1

    artifacts = [a.strip() for a in artifacts_str.split(",") if a.strip()]
    if not artifacts:
        print("PROMOTED=0")
        return 0

    proj = Path(project)
    ws = Path(workspace)

    if not proj.is_dir():
        print("ERROR=project_not_found")
        print(f"ERROR_DETAIL=Project directory not found: {project}")
        return 1
    if not ws.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Workspace directory not found: {workspace}")
        return 1

    promoted = 0
    for artifact in artifacts:
        src = ws / artifact
        dst = proj / artifact

        if not src.exists():
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

        try:
            git("add", artifact, cwd=project)
            promoted += 1
        except subprocess.CalledProcessError:
            pass

    if promoted > 0:
        try:
            git("commit", "-m", "docs(work-end): promote artifacts from workspace", cwd=project)
        except subprocess.CalledProcessError as e:
            if "nothing to commit" not in e.stdout and "nothing to commit" not in e.stderr:
                print("ERROR=commit_failed")
                print(f"ERROR_DETAIL=Failed to commit: {e.stderr.strip()}")
                return 1

        try:
            git("push", cwd=project)
            print("PUSHED=yes")
        except subprocess.CalledProcessError as e:
            print("PUSHED=no")
            print(f"PUSH_ERROR={e.stderr.strip()}")

    print(f"PROMOTED={promoted}")
    return 0


def cleanup_specs(workspace: str, params: dict[str, str]) -> int:
    branch = params.get("branch", "")

    if not branch:
        print("ERROR=missing_branch")
        print("ERROR_DETAIL=branch= argument required")
        return 1

    ws = Path(workspace)
    if not ws.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Workspace directory not found: {workspace}")
        return 1

    specs_dir = ws / "specs" / branch
    if not specs_dir.is_dir():
        print("CLEANED=0")
        return 0

    # Count files before removal
    count = sum(1 for _ in specs_dir.iterdir())
    shutil.rmtree(specs_dir)

    try:
        git("add", "-A", cwd=workspace)
        git("commit", "-m", "chore(work-end): cleanup promoted specs", cwd=workspace)
    except subprocess.CalledProcessError as e:
        if "nothing to commit" not in e.stdout and "nothing to commit" not in e.stderr:
            print("ERROR=commit_failed")
            print(f"ERROR_DETAIL=Failed to commit cleanup: {e.stderr.strip()}")
            return 1

    try:
        git("push", cwd=workspace)
        print("PUSHED=yes")
    except subprocess.CalledProcessError as e:
        print("PUSHED=no")
        print(f"PUSH_ERROR={e.stderr.strip()}")

    print(f"CLEANED={count}")
    return 0


def close_issues(repo: str, params: dict[str, str]) -> int:
    covers_str = params.get("covers", "")

    if not covers_str:
        print("ERROR=missing_covers")
        print("ERROR_DETAIL=covers= argument required")
        return 1

    issues = [n.strip() for n in covers_str.split(",") if n.strip()]
    if not issues:
        print("CLOSED=0")
        return 0

    closed = 0
    errors = []
    for issue_num in issues:
        try:
            subprocess.run(
                ["gh", "issue", "close", issue_num, "--repo", repo],
                capture_output=True, text=True, check=True,
            )
            closed += 1
        except subprocess.CalledProcessError as e:
            errors.append(f"#{issue_num}: {e.stderr.strip()}")

    if errors and closed == 0:
        print("ERROR=gh_failed")
        print(f"ERROR_DETAIL=All issue closes failed: {'; '.join(errors)}")
        return 1

    print(f"CLOSED={closed}")
    if errors:
        print(f"ERRORS={'; '.join(errors)}")
    return 0


def archive_plans(workspace: str, params: dict[str, str]) -> int:
    branch = params.get("branch", "")
    if not branch:
        print("ERROR=missing_branch")
        print("ERROR_DETAIL=branch= argument required")
        return 1

    ws = Path(workspace)
    plans_dir = ws / "plans"
    if not plans_dir.is_dir():
        print("ARCHIVED=0")
        return 0

    plan_files = [
        f for f in plans_dir.iterdir()
        if f.is_file() and f.suffix == ".md" and f.name != "INDEX.md"
    ]
    if not plan_files:
        print("ARCHIVED=0")
        return 0

    try:
        git("checkout", "main", cwd=workspace)
    except subprocess.CalledProcessError as e:
        print("ERROR=checkout_failed")
        print(f"ERROR_DETAIL=Failed to checkout main: {e.stderr.strip()}")
        return 1

    try:
        git("pull", "--rebase", "origin", "main", cwd=workspace)
    except subprocess.CalledProcessError:
        pass

    for pf in plan_files:
        rel = str(pf.relative_to(ws))
        try:
            git("checkout", branch, "--", rel, cwd=workspace)
        except subprocess.CalledProcessError:
            pass

    attic_dir = plans_dir / "attic" / branch
    attic_dir.mkdir(parents=True, exist_ok=True)
    archived = 0
    for pf in plan_files:
        src = ws / "plans" / pf.name
        if src.exists():
            shutil.move(str(src), str(attic_dir / pf.name))
            archived += 1

    if archived > 0:
        try:
            git("add", "-A", "plans/", cwd=workspace)
            git("commit", "-m", f"docs(work-end): archive plans from {branch}", cwd=workspace)
        except subprocess.CalledProcessError as e:
            if "nothing to commit" not in (e.stdout + e.stderr):
                print("ERROR=commit_failed")
                print(f"ERROR_DETAIL={e.stderr.strip()}")
                try:
                    git("checkout", branch, cwd=workspace)
                except subprocess.CalledProcessError:
                    pass
                return 1

        try:
            git("push", cwd=workspace)
            print("PUSHED=yes")
        except subprocess.CalledProcessError as e:
            print("PUSHED=no")
            print(f"PUSH_ERROR={e.stderr.strip()}")

    try:
        git("checkout", branch, cwd=workspace)
    except subprocess.CalledProcessError:
        pass

    print(f"ARCHIVED={archived}")
    return 0


SUBCOMMANDS = {
    "to-workspace-main": lambda args: to_workspace_main(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "to-project": lambda args: to_project(args[0], args[1], parse_args(args[2:])) if len(args) >= 2 else _usage(),
    "cleanup-specs": lambda args: cleanup_specs(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "close-issues": lambda args: close_issues(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "archive-plans": lambda args: archive_plans(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
}


def _usage() -> int:
    print(__doc__, file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) < 2:
        return _usage()

    subcmd = sys.argv[1]
    if subcmd not in SUBCOMMANDS:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        return _usage()

    return SUBCOMMANDS[subcmd](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
