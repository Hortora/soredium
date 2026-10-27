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

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from common import detect_topology, parse_args
from git_util import git, collect_slot_repos

# Path to remove_from_stack.py — resolve relative to this script's location
REMOVE_FROM_STACK = Path(__file__).parent.parent / "project" / "remove_from_stack.py"


def _plan_has_remaining(plan_path: Path) -> bool:
    """Check if a .plan has uncompleted queue items."""
    if not plan_path.exists():
        return False
    try:
        _project_dir = str(Path(__file__).resolve().parent.parent / "project")
        if _project_dir not in sys.path:
            sys.path.insert(0, _project_dir)
        from plan_io import read_plan, has_uncompleted_items
        state = read_plan(plan_path)
        if state is None:
            return False
        return has_uncompleted_items(state)
    except Exception:
        return False


def _reset_plan_state(plan_path: Path) -> None:
    """Reset .plan state from closing:* to active via lifecycle transition.

    No longer called from cleanup_scaffold — plan state management is
    handled by cleanup_pass in the orchestrator (#442). Kept for external
    callers that may still need it.
    """
    if not plan_path.exists():
        return
    _project_dir = str(Path(__file__).resolve().parent.parent / "project")
    if _project_dir not in sys.path:
        sys.path.insert(0, _project_dir)
    from lifecycle import TransitionResult, commit_transition, read_state
    current = read_state(plan_path)
    if current and current.startswith("closing:"):
        result = TransitionResult(
            from_state=current, new_state="active", event="reset_for_next",
        )
        try:
            commit_transition(plan_path, result)
        except Exception as e:
            print(f"WARN=reset_plan_state_failed: {e}")


def cleanup_scaffold(workspace: str, params: dict[str, str]) -> int:
    single_repo = params.get("single-repo", "no")

    ws = Path(workspace)
    if not ws.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Workspace directory not found: {workspace}")
        return 1

    plan_path = ws / ".plan"
    preserve_plan = _plan_has_remaining(plan_path)
    if preserve_plan:
        print(f"PLAN_PRESERVED=yes")

    files_to_remove = []
    scaffold_names = ["JOURNAL.md", ".execute-progress",
                      ".land-ledger.jsonl", ".artifacts-promoted",
                      ".close-progress", ".close-report.json",
                      ".close-log.jsonl", ".wrap-log.jsonl"]
    if not preserve_plan:
        scaffold_names.insert(0, ".plan")
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

    r = git(workspace, "rm", "-f", "--ignore-unmatch", *files_to_remove)
    if r.returncode != 0:
        print("ERROR=rm_failed")
        print(f"ERROR_DETAIL=Failed to remove scaffold files: {r.stderr.strip()}")
        return 1

    # Remove design/ dir if empty
    design_dir = ws / "design"
    if design_dir.is_dir() and not any(design_dir.iterdir()):
        design_dir.rmdir()

    slot_path = params.get("slot_path", "")
    if slot_path:
        _slot_dir = str(Path(__file__).resolve().parent.parent / "work-slot")
        if _slot_dir not in sys.path:
            sys.path.insert(0, _slot_dir)
        from slot_claude import clear_occupant_pid
        clear_occupant_pid(Path(slot_path))

    r = git(workspace, "commit", "-m", "chore(work-end): cleanup branch scaffold")
    if r.returncode != 0:
        if "nothing to commit" not in r.stdout and "nothing to commit" not in r.stderr:
            print("ERROR=commit_failed")
            print(f"ERROR_DETAIL=Failed to commit scaffold cleanup: {r.stderr.strip()}")
            return 1

    push_ok = False
    r = git(workspace, "push")
    if r.returncode == 0:
        push_ok = True
    else:
        r = git(workspace, "push", "origin", "main")
        if r.returncode == 0:
            push_ok = True

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

    rel_path = str(stack_file.relative_to(ws))
    git(workspace, "add", rel_path)
    r = git(workspace, "commit", "-m", f"chore(work-end): remove {branch} from pause stack (closed)")
    if r.returncode != 0:
        if "nothing to commit" not in r.stdout and "nothing to commit" not in r.stderr:
            print("ERROR=commit_failed")
            print(f"ERROR_DETAIL=Failed to commit stack cleanup: {r.stderr.strip()}")
            return 1

    git(workspace, "push")

    print("REMOVED=yes")
    return 0


def _abort_rebase_if_needed(repo_path: str) -> None:
    rebase_dir = Path(repo_path) / ".git" / "rebase-merge"
    rebase_apply = Path(repo_path) / ".git" / "rebase-apply"
    if rebase_dir.exists() or rebase_apply.exists():
        git(repo_path, "rebase", "--abort")


def _safe_pull_rebase(repo_path: str, remote: str, branch: str = "main") -> None:
    r = git(repo_path, "pull", "--rebase", remote, branch)
    if r.returncode != 0:
        _abort_rebase_if_needed(repo_path)


def checkout_main(project: str, workspace: str, slot_path: str = "") -> int:
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

    repos = collect_slot_repos(slot_path, project, workspace) if slot_path else [(project, "project"), (workspace, "workspace")]

    failures = []
    for repo_path, label in repos:
        _abort_rebase_if_needed(repo_path)

        status = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain", "-u"],
            capture_output=True, text=True,
        )
        if status.stdout.strip():
            stash = git(repo_path, "stash", "-u", "-m", "work-end: stash before checkout main")
            if stash.returncode != 0:
                git(repo_path, "add", "-A")
                git(repo_path, "commit", "--allow-empty", "-m",
                    "chore: commit lifecycle state before branch switch")

        r = git(repo_path, "checkout", "main")
        if r.returncode != 0:
            failures.append(f"{label}: {r.stderr.strip()}")

    if failures:
        print("ERROR=checkout_failed")
        print(f"ERROR_DETAIL=Failed to checkout main in: {'; '.join(failures)}")
        return 1

    fork_remote, blessed_remote = detect_topology(project)
    proj_remote = blessed_remote if blessed_remote else fork_remote or "origin"
    _safe_pull_rebase(project, proj_remote)
    _safe_pull_rebase(workspace, "origin")

    for repo_path, label in repos:
        head = git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        if head.stdout.strip() != "main":
            print(f"ERROR=not_on_main")
            print(f"ERROR_DETAIL={label} HEAD is '{head.stdout.strip()}', expected 'main'")
            return 1

    print(f"SWITCHED=yes")
    print(f"REPOS_SWITCHED={len(repos)}")
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
        git(repo_path, "add", "-A")
        r = git(repo_path, "commit", "-m", "WIP: session wrap — uncommitted changes")
        if r.returncode == 0:
            print(f"COMMITTED_{label.upper()}=yes")
        else:
            if "nothing to commit" not in (r.stdout or "") and "nothing to commit" not in (r.stderr or ""):
                print(f"WARN=commit_failed_{label}")
    print("WIP_COMMITTED=yes")
    return 0


SUBCOMMANDS = {
    "cleanup-scaffold": lambda args: cleanup_scaffold(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "cleanup-stack": lambda args: cleanup_stack(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "checkout-main": lambda args: checkout_main(args[0], args[1], slot_path=parse_args(args[2:]).get("slot_path", "")) if len(args) >= 2 else _usage(),
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
