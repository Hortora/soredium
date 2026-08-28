#!/usr/bin/env python3
"""
Handle branch closing operations: scaffold cleanup, stack cleanup,
and checkout-main.

Usage: python3 branch_cleanup.py <subcommand> <args...>

Subcommands:
    cleanup-scaffold    <workspace> [single-repo=<yes/no>]
    cleanup-stack       <workspace> branch=<name>
    checkout-main       <project> <workspace>
    wip-commit          <project> <workspace>

Output (KEY=value lines):
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

from common import detect_topology, parse_args

# Path to remove_from_stack.py — resolve relative to this script's location
REMOVE_FROM_STACK = Path(__file__).parent.parent / "project" / "remove_from_stack.py"


def git(*cmd: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd] + list(cmd),
        capture_output=True, text=True, check=True,
    )


def cleanup_scaffold(workspace: str, params: dict[str, str]) -> int:
    single_repo = params.get("single-repo", "no")

    ws = Path(workspace)
    if not ws.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Workspace directory not found: {workspace}")
        return 1

    files_to_remove = []
    scaffold_names = [".plan", "JOURNAL.md", ".execute-progress",
                      ".land-ledger.jsonl", ".artifacts-promoted",
                      ".close-progress", ".close-report.json",
                      ".close-log.jsonl", ".wrap-log.jsonl"]
    for name in scaffold_names:
        if (ws / name).exists():
            files_to_remove.append(name)
        if (ws / "design" / name).exists():
            files_to_remove.append(f"design/{name}")
    for legacy in (".meta", ".epic"):
        if (ws / legacy).exists():
            files_to_remove.append(legacy)
        if (ws / "design" / legacy).exists():
            files_to_remove.append(f"design/{legacy}")

    if not files_to_remove:
        print("CLEANED=yes")
        return 0

    try:
        git("rm", "-f", "--ignore-unmatch", *files_to_remove, cwd=workspace)
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

    push_ok = False
    try:
        git("push", cwd=workspace)
        push_ok = True
    except subprocess.CalledProcessError:
        try:
            git("push", "origin", "main", cwd=workspace)
            push_ok = True
        except subprocess.CalledProcessError:
            pass

    print("CLEANED=yes")
    if not push_ok:
        print("PUSH_WARNING=scaffold cleanup committed locally but not pushed — stale .plan may persist on remote")
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

    stack_file = ws / ".pause-stack"
    if not stack_file.exists():
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
        rel_path = str(stack_file.relative_to(ws))
        git("add", rel_path, cwd=workspace)
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

    # Commit any dirty state before switching — the orchestrator modifies
    # workspace files (.plan, .land-ledger.jsonl) during close, and uncommitted
    # changes block git checkout.
    for repo_path, label in [(project, "project"), (workspace, "workspace")]:
        status = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain"],
            capture_output=True, text=True,
        )
        if status.stdout.strip():
            try:
                git("add", "-A", cwd=repo_path)
                git("commit", "-m", "chore: commit lifecycle state before branch switch", cwd=repo_path)
            except subprocess.CalledProcessError:
                pass

    # Checkout main in both repos
    for repo_path, label in [(project, "project"), (workspace, "workspace")]:
        try:
            git("checkout", "main", cwd=repo_path)
        except subprocess.CalledProcessError as e:
            print(f"ERROR=checkout_failed")
            print(f"ERROR_DETAIL=Failed to checkout main in {label}: {e.stderr.strip()}")
            return 1

    # Pull --rebase from blessed remote (non-fatal if fails — no remote)
    fork_remote, blessed_remote = detect_topology(project)
    proj_remote = blessed_remote if blessed_remote else fork_remote or "origin"
    try:
        git("pull", "--rebase", proj_remote, "main", cwd=project)
    except subprocess.CalledProcessError:
        pass
    try:
        git("pull", "--rebase", "origin", "main", cwd=workspace)
    except subprocess.CalledProcessError:
        pass

    print("SWITCHED=yes")
    return 0


def wip_commit(project: str, workspace: str) -> int:
    """Commit all uncommitted changes as WIP in both repos."""
    for repo_path, label in [(project, "project"), (workspace, "workspace")]:
        p = Path(repo_path)
        if not p.is_dir():
            continue
        result = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain"],
            capture_output=True, text=True,
        )
        if not result.stdout.strip():
            continue
        try:
            git("add", "-A", cwd=repo_path)
            git("commit", "-m", "WIP: session wrap — uncommitted changes", cwd=repo_path)
            print(f"COMMITTED_{label.upper()}=yes")
        except subprocess.CalledProcessError as e:
            if "nothing to commit" not in (e.stdout or "") and "nothing to commit" not in (e.stderr or ""):
                print(f"WARN=commit_failed_{label}")
    print("WIP_COMMITTED=yes")
    return 0


SUBCOMMANDS = {
    "cleanup-scaffold": lambda args: cleanup_scaffold(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "cleanup-stack": lambda args: cleanup_stack(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "checkout-main": lambda args: checkout_main(args[0], args[1]) if len(args) >= 2 else _usage(),
    "wip-commit": lambda args: wip_commit(args[0], args[1]) if len(args) >= 2 else _usage(),
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
