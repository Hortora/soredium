#!/usr/bin/env python3
"""
Handle branch closing operations: EPIC-CLOSED marker, scaffold cleanup, stack
cleanup, and checkout-main.

Usage: python3 branch_cleanup.py <subcommand> <args...>

Subcommands:
    create-epic-closed  <workspace> branch=<name> date=<YYYY-MM-DD>
                        issues=<csv> [single-repo=<yes/no>]
    cleanup-scaffold    <workspace> [single-repo=<yes/no>]
    cleanup-stack       <workspace> branch=<name>
    checkout-main       <project> <workspace>

Output (KEY=value lines):
    CREATED=yes         (for create-epic-closed)
    CLEANED=yes         (for cleanup-scaffold)
    REMOVED=yes|no      (for cleanup-stack)
    SWITCHED=yes        (for checkout-main)

Error output:
    ERROR=<error_code>
    ERROR_DETAIL=<message>

Exit codes:
    0  success
    1  missing required args, I/O error, or operation failure
"""

import subprocess
import sys
from pathlib import Path

from common import parse_args

# Path to remove_from_stack.py — resolve relative to this script's location
REMOVE_FROM_STACK = Path(__file__).parent.parent / "project" / "remove_from_stack.py"


def git(*cmd: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd] + list(cmd),
        capture_output=True, text=True, check=True,
    )


def create_epic_closed(workspace: str, params: dict[str, str]) -> int:
    branch = params.get("branch", "")
    close_date = params.get("date", "")
    issues = params.get("issues", "")
    single_repo = params.get("single-repo", "no")

    if not branch:
        print("ERROR=missing_branch")
        print("ERROR_DETAIL=branch= argument required")
        return 1
    if not close_date:
        print("ERROR=missing_date")
        print("ERROR_DETAIL=date= argument required")
        return 1
    if not issues:
        print("ERROR=missing_issues")
        print("ERROR_DETAIL=issues= argument required")
        return 1

    ws = Path(workspace)
    if not ws.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Workspace directory not found: {workspace}")
        return 1

    # In single-repo mode, checkout branch first
    if single_repo == "yes":
        try:
            git("checkout", branch, cwd=workspace)
        except subprocess.CalledProcessError as e:
            print("ERROR=checkout_failed")
            print(f"ERROR_DETAIL=Failed to checkout {branch}: {e.stderr.strip()}")
            return 1

    # Create the EPIC-CLOSED.md file
    design_dir = ws / "design"
    design_dir.mkdir(parents=True, exist_ok=True)

    content = f"""# Branch Closed: {branch}

**Date:** {close_date}
**Issues:** {issues}
**Status:** merged to main
"""

    (design_dir / "EPIC-CLOSED.md").write_text(content)

    try:
        git("add", "design/EPIC-CLOSED.md", cwd=workspace)
        git("commit", "-m", f"docs({branch}): mark closed", cwd=workspace)
    except subprocess.CalledProcessError as e:
        print("ERROR=commit_failed")
        print(f"ERROR_DETAIL=Failed to commit EPIC-CLOSED.md: {e.stderr.strip()}")
        return 1

    try:
        git("push", cwd=workspace)
    except subprocess.CalledProcessError:
        # Push failure is non-fatal for marking closed
        pass

    # In single-repo mode, switch back to main
    if single_repo == "yes":
        try:
            git("checkout", "main", cwd=workspace)
        except subprocess.CalledProcessError:
            pass

    print("CREATED=yes")
    return 0


def cleanup_scaffold(workspace: str, params: dict[str, str]) -> int:
    single_repo = params.get("single-repo", "no")

    ws = Path(workspace)
    if not ws.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Workspace directory not found: {workspace}")
        return 1

    files_to_remove = []
    meta_path = ws / "design" / ".meta"
    journal_path = ws / "design" / "JOURNAL.md"

    if meta_path.exists():
        files_to_remove.append("design/.meta")
    if journal_path.exists():
        files_to_remove.append("design/JOURNAL.md")

    if not files_to_remove:
        print("CLEANED=yes")
        return 0

    try:
        git("rm", "-f", *files_to_remove, cwd=workspace)
    except subprocess.CalledProcessError as e:
        print("ERROR=rm_failed")
        print(f"ERROR_DETAIL=Failed to remove scaffold files: {e.stderr.strip()}")
        return 1

    # Remove design/ dir if empty
    design_dir = ws / "design"
    if design_dir.is_dir() and not any(design_dir.iterdir()):
        design_dir.rmdir()

    try:
        git("commit", "-m", "chore(work-end): cleanup branch scaffold", cwd=workspace)
    except subprocess.CalledProcessError as e:
        if "nothing to commit" not in e.stdout and "nothing to commit" not in e.stderr:
            print("ERROR=commit_failed")
            print(f"ERROR_DETAIL=Failed to commit scaffold cleanup: {e.stderr.strip()}")
            return 1

    try:
        git("push", cwd=workspace)
    except subprocess.CalledProcessError:
        # Push failure is non-fatal
        pass

    print("CLEANED=yes")
    return 0


def cleanup_stack(workspace: str, params: dict[str, str]) -> int:
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

    stack_file = ws / "design" / ".pause-stack"

    if not stack_file.exists():
        print("REMOVED=no")
        return 0

    content = stack_file.read_text()
    if f"branch: {branch}" not in content:
        print("REMOVED=no")
        return 0

    # Delegate to remove_from_stack.py
    try:
        subprocess.run(
            [sys.executable, str(REMOVE_FROM_STACK), str(stack_file), branch],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        print("ERROR=stack_remove_failed")
        print(f"ERROR_DETAIL=Failed to remove from stack: {e.stderr.strip()}")
        return 1

    try:
        git("add", "design/.pause-stack", cwd=workspace)
        git("commit", "-m", f"chore(work-end): remove {branch} from pause stack (closed)", cwd=workspace)
    except subprocess.CalledProcessError as e:
        if "nothing to commit" not in e.stdout and "nothing to commit" not in e.stderr:
            print("ERROR=commit_failed")
            print(f"ERROR_DETAIL=Failed to commit stack cleanup: {e.stderr.strip()}")
            return 1

    try:
        git("push", cwd=workspace)
    except subprocess.CalledProcessError:
        # Push failure is non-fatal
        pass

    print("REMOVED=yes")
    return 0


def checkout_main(project: str, workspace: str) -> int:
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

    # Checkout main in both repos
    for repo_path, label in [(project, "project"), (workspace, "workspace")]:
        try:
            git("checkout", "main", cwd=repo_path)
        except subprocess.CalledProcessError as e:
            print(f"ERROR=checkout_failed")
            print(f"ERROR_DETAIL=Failed to checkout main in {label}: {e.stderr.strip()}")
            return 1

    # Pull --rebase in both (non-fatal if fails — no remote)
    for repo_path in [project, workspace]:
        try:
            git("pull", "--rebase", "origin", "main", cwd=repo_path)
        except subprocess.CalledProcessError:
            pass

    print("SWITCHED=yes")
    return 0


SUBCOMMANDS = {
    "create-epic-closed": lambda args: create_epic_closed(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "cleanup-scaffold": lambda args: cleanup_scaffold(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "cleanup-stack": lambda args: cleanup_stack(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "checkout-main": lambda args: checkout_main(args[0], args[1]) if len(args) >= 2 else _usage(),
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
