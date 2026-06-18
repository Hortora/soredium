#!/usr/bin/env python3
"""
work-resume executable blocks: checkout, rebase, reset-wip.

Usage:
  resume_exec.py checkout-branches <project> <workspace> branch=<name>
  resume_exec.py rebase <project> <workspace> base-branch=<base>
  resume_exec.py reset-wip <project> <workspace>
"""

import subprocess
import sys
from pathlib import Path


def run(
    cmd: list[str],
    cwd: Path | str | None = None,
    check: bool = True,
    capture: bool = True,
) -> tuple[int, str, str]:
    """Run command as list, return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def checkout_branches(project: str, workspace: str, branch: str) -> int:
    """Checkout branch in both repos and verify."""
    project_path = Path(project)
    workspace_path = Path(workspace)

    # Verify branch exists in both repos
    exit_code, _, _ = run(
        ["git", "rev-parse", "--verify", branch], cwd=project_path, check=False
    )
    if exit_code != 0:
        print("ERROR=branch_not_found")
        return 1

    exit_code, _, _ = run(
        ["git", "rev-parse", "--verify", branch], cwd=workspace_path, check=False
    )
    if exit_code != 0:
        print("ERROR=branch_not_found")
        return 1

    # Checkout in both repos
    run(["git", "checkout", branch], cwd=project_path)
    run(["git", "checkout", branch], cwd=workspace_path)

    # Verify both are on the same branch
    _, project_branch, _ = run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_path
    )
    _, workspace_branch, _ = run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace_path
    )

    if project_branch != workspace_branch:
        print(
            f"ERROR=branch_mismatch project={project_branch} workspace={workspace_branch}"
        )
        return 1

    print("CHECKED_OUT=yes")
    return 0


def rebase(project: str, workspace: str, base_branch: str) -> int:
    """Rebase project onto base branch, best-effort workspace rebase."""
    project_path = Path(project)
    workspace_path = Path(workspace)

    # Check if already up to date
    exit_code, merge_base, _ = run(
        ["git", "merge-base", "HEAD", base_branch], cwd=project_path, check=False
    )
    _, base_sha, _ = run(
        ["git", "rev-parse", base_branch], cwd=project_path, check=False
    )

    if merge_base == base_sha:
        # Already up to date
        print("REBASED=skipped")
        return 0

    # Rebase project onto base branch
    exit_code, _, stderr = run(
        ["git", "rebase", base_branch], cwd=project_path, check=False
    )
    if exit_code != 0:
        print("ERROR=rebase_conflict")
        return 1

    # Best-effort workspace rebase (don't fail if it errors)
    run(["git", "rebase", "main"], cwd=workspace_path, check=False)

    print("REBASED=yes")
    return 0


def reset_wip(project: str, workspace: str) -> int:
    """Reset WIP commits if present in either repo."""
    project_path = Path(project)
    workspace_path = Path(workspace)

    reset_count = 0

    # Check project for WIP commit
    _, project_subject, _ = run(
        ["git", "log", "-1", "--format=%s"], cwd=project_path
    )
    if project_subject.startswith("WIP:"):
        run(["git", "reset", "HEAD~1"], cwd=project_path)
        reset_count += 1

    # Check workspace for WIP commit
    _, workspace_subject, _ = run(
        ["git", "log", "-1", "--format=%s"], cwd=workspace_path
    )
    if workspace_subject.startswith("WIP:"):
        run(["git", "reset", "HEAD~1"], cwd=workspace_path)
        reset_count += 1

    if reset_count > 0:
        print("RESET=yes")
    else:
        print("RESET=no")

    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    if cmd == "checkout-branches":
        if len(sys.argv) != 5:
            print("Usage: resume_exec.py checkout-branches <project> <workspace> branch=<name>")
            return 1

        project = sys.argv[2]
        workspace = sys.argv[3]
        branch_arg = sys.argv[4]

        if not branch_arg.startswith("branch="):
            print("Third argument must be branch=<name>")
            return 1

        branch = branch_arg.split("=", 1)[1]
        return checkout_branches(project, workspace, branch)

    elif cmd == "rebase":
        if len(sys.argv) != 5:
            print("Usage: resume_exec.py rebase <project> <workspace> base-branch=<base>")
            return 1

        project = sys.argv[2]
        workspace = sys.argv[3]
        base_arg = sys.argv[4]

        if not base_arg.startswith("base-branch="):
            print("Third argument must be base-branch=<base>")
            return 1

        base_branch = base_arg.split("=", 1)[1]
        return rebase(project, workspace, base_branch)

    elif cmd == "reset-wip":
        if len(sys.argv) != 4:
            print("Usage: resume_exec.py reset-wip <project> <workspace>")
            return 1

        project = sys.argv[2]
        workspace = sys.argv[3]
        return reset_wip(project, workspace)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
