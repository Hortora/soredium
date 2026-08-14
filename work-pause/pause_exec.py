#!/usr/bin/env python3
"""
pause_exec.py — Externalized operations for work-pause

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


def _resolve_clone_origin(repo: str) -> Path | None:
    """If repo is a git clone whose origin points to a local directory, return that path."""
    ok, url = run_git(repo, "remote", "get-url", "origin")
    if not ok:
        return None
    origin_path = Path(url)
    if origin_path.is_dir() and (origin_path / ".git").exists():
        return origin_path.resolve()
    return None


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


def push_and_stack(workspace: str, project: str, branch: str, issue: str, base_branch: str) -> int:
    """
    Push project/workspace branches, checkout base, pull, add stack entry.

    Push failures are non-fatal. Stack push MUST succeed.

    When workspace is a slot clone (origin points to a local directory),
    the stack entry is written to the original workspace's pause stack
    with a slot= field pointing to the slot directory.

    Output:
        STACKED=yes
        PROJECT_PUSHED=yes|no
        WORKSPACE_PUSHED=yes|no
    """
    # Detect slot context: is workspace a clone of a local repo?
    original_workspace = _resolve_clone_origin(workspace)
    slot_dir: Path | None = None
    stack_workspace: str  # repo where the stack entry gets committed
    if original_workspace is not None:
        slot_dir = _resolve_slot_dir(Path(workspace))
        stack_workspace = str(original_workspace)
    else:
        stack_workspace = workspace

    # Push project branch (non-fatal)
    # In slot mode, origin is a local path — do two-hop push
    original_project = _resolve_clone_origin(project)
    project_push_ok, _ = run_git(project, "push", "origin", branch)
    if project_push_ok and original_project is not None:
        run_git(str(original_project), "push", "origin", branch)
    print(f"PROJECT_PUSHED={'yes' if project_push_ok else 'no'}")

    # Push workspace branch (non-fatal)
    workspace_push_ok, _ = run_git(workspace, "push", "origin", branch)
    if workspace_push_ok and original_workspace is not None:
        run_git(str(original_workspace), "push", "origin", branch)
    print(f"WORKSPACE_PUSHED={'yes' if workspace_push_ok else 'no'}")

    # Checkout base in project
    checkout_ok, _ = run_git(project, "checkout", base_branch)
    if not checkout_ok:
        print("ERROR=project_checkout_failed")
        return 1

    # Checkout main in workspace clone (independent branches — always works)
    ws_checkout_ok, _ = run_git(workspace, "checkout", "main")
    if not ws_checkout_ok:
        print("ERROR=workspace_checkout_failed")
        return 1

    # Pull project (skip if no upstream configured)
    has_upstream, _ = run_git(project, "rev-parse", "--abbrev-ref", "@{u}")
    if has_upstream:
        pull_ok, _ = run_git(project, "pull", "--rebase")
        if not pull_ok:
            print("ERROR=project_pull_failed")
            return 1

    # For stack operations, ensure we're on main in the stack workspace
    if original_workspace is not None:
        checkout_ok, _ = run_git(stack_workspace, "checkout", "main")
        if not checkout_ok:
            print("ERROR=original_workspace_checkout_failed")
            return 1
        has_remote, _ = run_git(stack_workspace, "remote", "get-url", "origin")
        if has_remote:
            pull_ok, _ = run_git(stack_workspace, "pull", "--rebase", "origin", "main")
            if not pull_ok:
                print("ERROR=original_workspace_pull_failed")
                return 1
    else:
        has_remote, _ = run_git(workspace, "remote", "get-url", "origin")
        if has_remote:
            ws_pull_ok, _ = run_git(workspace, "pull", "--rebase", "origin", "main")
            if not ws_pull_ok:
                print("ERROR=workspace_pull_failed")
                return 1

    # Push stack entry to the stack workspace (original if slot, else workspace)
    stack_file = Path(stack_workspace) / "design" / ".pause-stack"
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
            from slot_manager import is_slot_path as _is_slot_path
            if _is_slot_path(project):
                plan_info = _plan_detect(Path(project))
        if plan_info:
            active = plan_info.get("active_issue")
            if active:
                push_args.append(f"epic_active_issue={active}")
    except ImportError:
        pass

    try:
        result = subprocess.run(
            push_args,
            capture_output=True,
            text=True,
            check=True
        )
        # Parse STACK_DEPTH from output
        depth = None
        for line in result.stdout.splitlines():
            if line.startswith("STACK_DEPTH="):
                depth = line.split("=")[1]
                break

        if depth is None:
            print("ERROR=stack_depth_missing")
            return 1

        # Add, commit, push stack change on the stack workspace
        add_ok, _ = run_git(stack_workspace, "add", "design/.pause-stack")
        if not add_ok:
            print("ERROR=stack_add_failed")
            return 1

        commit_msg = f"chore: pause {branch} — stack depth {depth}"
        commit_ok, _ = run_git(stack_workspace, "commit", "-m", commit_msg)
        if not commit_ok:
            print("ERROR=stack_commit_failed")
            return 1

        # Push stack commit (only if remote is configured)
        has_ws_remote, _ = run_git(stack_workspace, "remote", "get-url", "origin")
        if has_ws_remote:
            push_stack_ok, _ = run_git(stack_workspace, "push")
            if not push_stack_ok:
                # If stack push fails, abort by popping the entry
                subprocess.run(
                    ["python3", str(stack_script), "pop", str(stack_file), branch],
                    check=False
                )
                print("ERROR=stack_push_failed")
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

    except subprocess.CalledProcessError:
        print("ERROR=stack_script_failed")
        return 1


PAUSE_STEPS = ["wip_project", "wip_workspace", "stack_push", "checkout_main"]


def _intent_path(workspace: str) -> Path:
    return Path(workspace) / "design" / ".pausing"


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
