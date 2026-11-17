#!/usr/bin/env python3
"""
pause_exec.py — Externalized operations for work-pause

Pausing never pushes, pulls or stashes. The paused branch is backed up by the
canonical repo (project/canonical_sync.py); in a slot the stack entry is landed
in the canonical workspace the same way any other work is.

Usage:
    python3 pause_exec.py commit-wip <repo> message=<msg>
    python3 pause_exec.py push-and-stack <workspace> <project> branch=<name> issue=<N> base-branch=<base>

Exit codes:
    0  success
    1  error

Output: KEY=value lines
"""

import os
import sys
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None


def run_git(repo: str, *args: str) -> tuple[bool, str]:
    """Run git command. Returns (success, stdout)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Library API — typed interface for command layer
# ---------------------------------------------------------------------------

@dataclass
class PauseWipResult:
    committed: bool
    repo: str
    message: str | None = None
    error: str | None = None


def commit_wip_typed(repo: str, message: str) -> PauseWipResult:
    """Check if repo has uncommitted changes. If dirty, commit as WIP."""
    success, status_out = run_git(repo, "status", "--short")
    if not success:
        return PauseWipResult(False, repo, error="git_status_failed")

    if not status_out.strip():
        return PauseWipResult(False, repo)

    add_ok, _ = run_git(repo, "add", "-A")
    if not add_ok:
        return PauseWipResult(False, repo, error="git_add_failed")

    commit_ok, _ = run_git(repo, "commit", "-m", message)
    if not commit_ok:
        return PauseWipResult(False, repo, error="commit_failed")

    return PauseWipResult(True, repo, message)


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------

def commit_wip(repo: str, message: str) -> int:
    """
    Check if repo has uncommitted changes. If dirty, commit as WIP.

    Output:
        COMMITTED=yes|clean
    """
    success, status_out = run_git(repo, "status", "--short")
    if not success:
        print("ERROR=git_status_failed")
        return 1

    if not status_out.strip():
        print("COMMITTED=clean")
        return 0

    # Dirty — add and commit
    add_ok, _ = run_git(repo, "add", "-A")
    if not add_ok:
        print("ERROR=git_add_failed")
        return 1

    commit_ok, _ = run_git(repo, "commit", "-m", message)
    if not commit_ok:
        print("ERROR=commit_failed")
        return 1

    print("COMMITTED=yes")
    return 0


def _canonical_sync():
    project_dir = str(Path(__file__).resolve().parent.parent / "project")
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    import canonical_sync
    return canonical_sync


def _resolve_slot_dir(clone_path: Path) -> Path | None:
    """Given a clone inside a slot (family/slots/N/repo or family/worktrees/N/repo), return the slot dir."""
    parts = clone_path.resolve().parts
    for name in ("slots", "worktrees"):
        try:
            idx = parts.index(name)
            if idx + 1 < len(parts):
                return Path(*parts[:idx + 2])
        except ValueError:
            continue
    return None


def _commit_leftovers(repo: str, branch: str) -> bool:
    """Commit anything still uncommitted onto the paused branch.

    Files written after the WIP commit (progress logs, hook output) used to be
    stashed before the checkout, where they were easy to lose. They go into a
    commit on the branch they belong to instead.
    """
    ok, status_out = run_git(repo, "status", "--short")
    if not ok or not status_out.strip():
        return False
    run_git(repo, "add", "-A")
    committed, _ = run_git(repo, "commit", "-m", f"WIP: pause {branch} (late changes)")
    if committed:
        print(f"LATE_WIP={Path(repo).name}")
    return committed


def _back_up(cs, repo: str, branch: str, label: str) -> None:
    """Ask the canonical repo to keep a copy of the paused branch. Never fatal, never silent."""
    try:
        ref = cs.backup(repo, branch)
        print(f"{label}_BACKED_UP={ref}")
        if cs.is_clone(repo):
            try:
                where = cs.backup_offsite(cs.locate(repo), ref)
                print(f"{label}_OFFSITE={where}")
            except cs.SyncError as error:
                print(f"{label}_OFFSITE=failed")
                print(f"WARN={error.detail}")
    except cs.SyncError as error:
        print(f"{label}_BACKED_UP=no")
        print(f"WARN={error.detail}")


def push_and_stack(workspace: str, project: str, branch: str, issue: str, base_branch: str) -> int:
    """
    Back the paused branch up, put both checkouts on the base branch, add the stack entry.

    Nothing is pushed, pulled or stashed, and no checkout but the session's own
    is switched. In a slot clone the stack entry is committed in the clone's
    workspace and landed in the canonical workspace through canonical_sync, so
    every session sees it, with a slot= field pointing at the slot directory.

    Output:
        STACKED=yes
        PROJECT_BACKED_UP=<ref>|no      (the canonical repo's copy of the branch)
        WORKSPACE_BACKED_UP=<ref>|no
        *_OFFSITE=<remote>|none|failed  (slot clones only)
        LATE_WIP=<repo>                 (leftover changes committed onto the branch)
        WARN=<detail>
    """
    cs = _canonical_sync()
    try:
        workspace_is_clone = cs.is_clone(workspace)
    except cs.SyncError as error:
        print("ERROR=no_canonical")
        print(f"ERROR_DETAIL={error.detail}")
        return 1
    slot_dir: Path | None = _resolve_slot_dir(Path(workspace)) if workspace_is_clone else None

    # WIP-commit sibling repos in slot mode
    if slot_dir is not None:
        from git_util import collect_slot_repos
        for repo_path, label in collect_slot_repos(str(slot_dir), project, workspace):
            if repo_path in (project, workspace):
                continue
            ok, status_out = run_git(repo_path, "status", "--short")
            if ok and status_out.strip():
                run_git(repo_path, "add", "-A")
                run_git(repo_path, "commit", "-m", f"WIP: pause {branch}")
                print(f"SIBLING_COMMITTED={label}")

    _commit_leftovers(project, branch)
    _commit_leftovers(workspace, branch)

    _back_up(cs, project, branch, "PROJECT")
    _back_up(cs, workspace, branch, "WORKSPACE")

    # The session's own checkouts go to the base branch.
    checkout_ok, _ = run_git(project, "checkout", base_branch)
    if not checkout_ok:
        print("ERROR=project_checkout_failed")
        return 1
    ws_checkout_ok, _ = run_git(workspace, "checkout", "main")
    if not ws_checkout_ok:
        print("ERROR=workspace_checkout_failed")
        return 1

    # A slot clone's main may be behind the canonical workspace, which holds the
    # stack every session reads. Bring it up to date before adding to it.
    if workspace_is_clone:
        try:
            cs.rebase(workspace, "main")
        except cs.SyncError as error:
            print("ERROR=workspace_not_current")
            print(f"ERROR_DETAIL={error.detail}")
            return 1

    stack_file = Path(workspace) / ".pause-stack"
    repo_stack = Path(__file__).resolve().parent.parent / "project" / "stack.py"
    installed_stack = Path.home() / ".claude" / "skills" / "project" / "stack.py"
    stack_script = repo_stack if repo_stack.exists() else installed_stack

    push_args = [
        "python3", str(stack_script), "push", str(stack_file),
        f"branch={branch}", f"issue={issue}",
    ]
    if slot_dir is not None:
        push_args.append(f"slot={slot_dir}")

    plan_detect_dir = Path(__file__).resolve().parent.parent / "work-slot"
    if str(plan_detect_dir) not in sys.path:
        sys.path.insert(0, str(plan_detect_dir))
    try:
        from plan_manager import detect as _plan_detect
        plan_info = _plan_detect(Path(workspace))
        if plan_info is None:
            from slot_core import is_slot_path as _is_slot_path
            if _is_slot_path(project):
                plan_info = _plan_detect(Path(project))
        if plan_info:
            active = plan_info.get("active_issue")
            if active:
                push_args.append(f"epic_active_issue={active}")
    except ImportError:
        pass

    try:
        result = subprocess.run(push_args, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        print("ERROR=stack_script_failed")
        return 1

    depth = None
    for line in result.stdout.splitlines():
        if line.startswith("STACK_DEPTH="):
            depth = line.split("=")[1]
            break
    if depth is None:
        print("ERROR=stack_depth_missing")
        return 1

    add_ok, _ = run_git(workspace, "add", ".pause-stack")
    if not add_ok:
        print("ERROR=stack_add_failed")
        return 1
    commit_ok, _ = run_git(workspace, "commit", "-m",
                           f"chore: pause {branch} — stack depth {depth}",
                           "-m", "no-issue: pause stack bookkeeping")
    if not commit_ok:
        subprocess.run(["python3", str(stack_script), "pop", str(stack_file), branch], check=False)
        run_git(workspace, "reset", "-q", "--", ".pause-stack")
        print("ERROR=stack_commit_failed")
        return 1

    if workspace_is_clone:
        try:
            cs.land(workspace, "main")
        except cs.SyncError as error:
            # The entry is committed in the slot's workspace and will be carried to
            # canonical by the next landing; other sessions cannot see it until then.
            print("ERROR=stack_not_landed")
            print(f"ERROR_DETAIL={error.detail}")
            return 1

    print("STACKED=yes")

    if _wl:
        try:
            _conn = _wl.connect()
            _wl.record_work_pause(_conn, branch, project)
            _conn.close()
        except Exception:
            pass

    return 0


PAUSE_STEPS = ["wip_project", "wip_workspace", "stack_push", "checkout_main"]


def _intent_path(workspace: str) -> Path:
    return Path(workspace) / ".pausing"


def _write_intent_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".pausing.tmp")
    closed = False
    try:
        os.write(fd, content.encode())
        os.close(fd)
        closed = True
        os.replace(tmp, str(path))
    except Exception:
        if not closed:
            os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_intent(workspace: str, branch: str) -> int:
    lines = [
        f"branch: {branch}",
        f"started: {datetime.now(timezone.utc).isoformat()}",
    ]
    for step in PAUSE_STEPS:
        lines.append(f"{step}: pending")
    _write_intent_atomic(_intent_path(workspace), "\n".join(lines) + "\n")
    print("INTENT=written")
    return 0


def update_intent(workspace: str, step: str) -> int:
    path = _intent_path(workspace)
    if not path.exists():
        return 0
    content = path.read_text()
    updated = content.replace(f"{step}: pending", f"{step}: done")
    _write_intent_atomic(path, updated)
    print(f"INTENT_STEP={step}")
    return 0


def clear_intent(workspace: str) -> int:
    path = _intent_path(workspace)
    if path.exists():
        path.unlink()
    print("INTENT=cleared")
    return 0


def parse_kv_args(args: list[str]) -> dict[str, str]:
    """Parse key=value arguments into dict."""
    result = {}
    for arg in args:
        if "=" in arg:
            key, _, val = arg.partition("=")
            result[key] = val
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("ERROR=missing_subcommand")
        return 1

    cmd = sys.argv[1]

    if cmd == "commit-wip":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            return 1
        repo = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        message = kv.get("message")
        if not message:
            print("ERROR=missing_message")
            return 1
        return commit_wip(repo, message)

    elif cmd == "push-and-stack":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            return 1
        workspace = sys.argv[2]
        project = sys.argv[3]
        kv = parse_kv_args(sys.argv[4:])
        branch = kv.get("branch")
        issue = kv.get("issue")
        base_branch = kv.get("base-branch", "main")
        if not branch or not issue:
            print("ERROR=missing_branch_or_issue")
            return 1
        return push_and_stack(workspace, project, branch, issue, base_branch)

    elif cmd == "write-intent":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        workspace = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        branch = kv.get("branch", "")
        if not branch:
            print("ERROR=missing_branch")
            return 1
        return write_intent(workspace, branch)

    elif cmd == "update-intent":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        workspace = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        step = kv.get("step", "")
        if not step:
            print("ERROR=missing_step")
            return 1
        return update_intent(workspace, step)

    elif cmd == "clear-intent":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        return clear_intent(sys.argv[2])

    else:
        print("ERROR=unknown_subcommand")
        return 1


if __name__ == "__main__":
    sys.exit(main())
