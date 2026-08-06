#!/usr/bin/env python3
"""
branch_create.py — Externalized git operations for work-start

Subcommands:

    create-branches <project> <workspace> branch=<name> [base=<base>]
        Create matching branches in project and workspace atomically.
        Project branch from current HEAD (or <base> if provided).
        If project fails: abort, no cleanup.
        If workspace fails: delete project branch, abort.
        Output: CREATED=yes

    commit-scaffold <workspace> branch=<name>
        Stage and commit design/JOURNAL.md and design/.meta, then push.
        Output: COMMITTED=yes, PUSHED=yes|no

    sync-main <project> <workspace> [base=<branch>]
        Sync local main with remote before branch creation.
        Detects fork model (upstream, fork, or single remote) and
        applies the correct fetch/rebase/push sequence.
        Non-fatal — network errors warn but don't fail.
        Output: SYNCED=yes MODEL=upstream|fork|single [WARN=...]

Exit codes:
    0  success
    1  error
"""

import subprocess
import sys


def run_git(repo: str, *args: str) -> tuple[bool, str]:
    """Run git command. Returns (success, stdout)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def create_branches(project: str, workspace: str, branch: str, base: str | None) -> int:
    """Create branches in project and workspace atomically."""
    # Create project branch
    if base:
        ok, err = run_git(project, "checkout", "-b", branch, base)
    else:
        ok, err = run_git(project, "checkout", "-b", branch)

    if not ok:
        print(f"ERROR=project_branch_failed:{err}")
        return 1

    # Create workspace branch
    ok, err = run_git(workspace, "checkout", "-b", branch)
    if not ok:
        # Rollback: return project to previous branch, then delete
        run_git(project, "checkout", "-")
        run_git(project, "branch", "-D", branch)
        print(f"ERROR=workspace_branch_failed:{err}")
        return 1

    print("CREATED=yes")
    return 0


def commit_scaffold(workspace: str, branch: str) -> int:
    """Commit scaffold files and push."""
    import os
    files_to_add = ["design/JOURNAL.md", "design/.meta"]
    if os.path.exists(os.path.join(workspace, "design", ".plan")):
        files_to_add.append("design/.plan")
    if os.path.exists(os.path.join(workspace, "design", ".epic")):
        files_to_add.append("design/.epic")
    ok, _ = run_git(workspace, "add", *files_to_add)
    if not ok:
        print("ERROR=add_failed")
        return 1

    commit_msg = f"init({branch}): scaffold workspace branch"
    ok, _ = run_git(workspace, "commit", "-m", commit_msg)
    if not ok:
        print("ERROR=commit_failed")
        return 1

    # Push with -u (non-fatal)
    push_ok, _ = run_git(workspace, "push", "-u", "origin", branch)

    print("COMMITTED=yes")
    print(f"PUSHED={'yes' if push_ok else 'no'}")
    return 0


def sync_main(project: str, workspace: str, base: str) -> int:
    """Sync local base branch with remote before branch creation."""
    warnings: list[str] = []

    has_upstream, _ = run_git(project, "remote", "get-url", "upstream")
    has_fork, _ = run_git(project, "remote", "get-url", "fork")

    if has_upstream:
        model = "upstream"
        ok, _ = run_git(project, "fetch", "upstream")
        if not ok:
            warnings.append("fetch_upstream_failed")
        else:
            ok, _ = run_git(project, "rebase", f"upstream/{base}")
            if not ok:
                warnings.append("rebase_upstream_failed")
            else:
                ok, _ = run_git(project, "push", "origin", base, "--force-with-lease")
                if not ok:
                    warnings.append("push_origin_failed")
    elif has_fork:
        model = "fork"
        ok, _ = run_git(project, "fetch", "origin")
        if not ok:
            warnings.append("fetch_origin_failed")
        else:
            ok, _ = run_git(project, "rebase", f"origin/{base}")
            if not ok:
                warnings.append("rebase_origin_failed")
            else:
                ok, _ = run_git(project, "push", "fork", f"origin/{base}:{base}", "--force-with-lease")
                if not ok:
                    warnings.append("push_fork_failed")
    else:
        model = "single"
        ok, _ = run_git(project, "fetch", "origin")
        if not ok:
            warnings.append("fetch_origin_failed")
        else:
            ok, _ = run_git(project, "rebase", f"origin/{base}")
            if not ok:
                warnings.append("rebase_origin_failed")

    ws_ok, _ = run_git(workspace, "fetch", "origin")
    if not ws_ok:
        warnings.append("workspace_fetch_failed")
    else:
        ws_ok, _ = run_git(workspace, "rebase", "origin/main")
        if not ws_ok:
            warnings.append("workspace_rebase_failed")

    print(f"SYNCED=yes")
    print(f"MODEL={model}")
    for w in warnings:
        print(f"WARN={w}")
    return 0


def parse_kv_args(args: list[str]) -> dict[str, str]:
    """Parse key=value arguments into dict."""
    result: dict[str, str] = {}
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

    if cmd == "create-branches":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            return 1
        project = sys.argv[2]
        workspace = sys.argv[3]
        kv = parse_kv_args(sys.argv[4:])
        branch = kv.get("branch")
        if not branch:
            print("ERROR=missing_branch")
            return 1
        base = kv.get("base") or None
        return create_branches(project, workspace, branch, base)

    elif cmd == "commit-scaffold":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        workspace = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        branch = kv.get("branch")
        if not branch:
            print("ERROR=missing_branch")
            return 1
        return commit_scaffold(workspace, branch)

    elif cmd == "sync-main":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            return 1
        project = sys.argv[2]
        workspace = sys.argv[3]
        kv = parse_kv_args(sys.argv[4:])
        base = kv.get("base", "main")
        return sync_main(project, workspace, base)

    else:
        print("ERROR=unknown_subcommand")
        return 1


if __name__ == "__main__":
    sys.exit(main())
