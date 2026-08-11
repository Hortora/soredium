"""Start command — create branch, scaffold, plan."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from commands.events import (
    BranchCreated, StepProgress, StateChanged, CommandFailed,
)
from commands.registry import resolve_context, derive_actions


def execute(issues: list[int] | None = None, cwd: str | None = None,
            decide_fn: Callable | None = None, **_kwargs) -> list:
    """Create branch, scaffold, and plan for given issues."""
    events: list = []

    if not issues:
        events.append(CommandFailed("start", None, "no_issues",
                                    "No issue numbers provided", True))
        return events

    ctx = resolve_context(cwd)

    if ctx.state != "idle":
        events.append(CommandFailed("start", None, "not_idle",
                                    f"Cannot start: state is '{ctx.state}', expected 'idle'",
                                    False))
        return events

    work_start_dir = Path(__file__).parent.parent / "work-start"
    if str(work_start_dir) not in sys.path:
        sys.path.insert(0, str(work_start_dir))

    issue = issues[0]
    branch = f"issue-{issue}-work"

    # Step 1: Create branches
    events.append(StepProgress("start", "creating_branches", None))
    try:
        from branch_create import create_branches_typed
        result = create_branches_typed(
            ctx.project_path,
            ctx.workspace_path or ctx.project_path,
            branch,
        )
        if result.error:
            events.append(CommandFailed("start", "creating_branches",
                                        "branch_create_failed", result.error, True))
            return events
    except Exception as e:
        events.append(CommandFailed("start", "creating_branches",
                                    "exception", str(e), True))
        return events

    # Step 2: Scaffold
    events.append(StepProgress("start", "scaffolding", None))
    try:
        from scaffold import scaffold

        import subprocess
        sha_result = subprocess.run(
            ["git", "-C", ctx.project_path, "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        project_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"

        workspace = Path(ctx.workspace_path) if ctx.workspace_path else Path(ctx.project_path)
        scaffold_result = scaffold(
            workspace=workspace,
            branch=branch,
            project_sha=project_sha,
            issue=str(issue),
            issue_repo=ctx.owner_repo or "",
            covers=" ".join(str(i) for i in issues),
            plan=len(issues) > 1,
        )
    except Exception as e:
        events.append(CommandFailed("start", "scaffolding",
                                    "exception", str(e), True))
        return events

    events.append(BranchCreated(
        branch=branch,
        issues=issues,
        plan_path=scaffold_result.plan_path,
    ))

    # Emit StateChanged
    actions, suggested = derive_actions("active", ctx.stack_depth, len(issues) > 1)
    events.append(StateChanged("idle", "active", actions, suggested))

    return events
