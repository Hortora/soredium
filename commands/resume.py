"""Resume command — stack pop + checkout + rebase + reset WIP."""
from __future__ import annotations

import sys
from pathlib import Path

from commands.events import Resumed, StateChanged, CommandFailed
from commands.registry import resolve_context, derive_actions


def execute(branch: str | None = None, cwd: str | None = None, **_kwargs) -> list:
    """Pop from pause stack, checkout, rebase, reset WIP."""
    events: list = []
    ctx = resolve_context(cwd)

    if ctx.state not in ("idle", "paused"):
        events.append(CommandFailed("resume", None, "wrong_state",
                                    f"Cannot resume: state is '{ctx.state}'", False))
        return events

    project_dir = Path(__file__).parent.parent / "project"
    resume_dir = Path(__file__).parent.parent / "work-resume"
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    if str(resume_dir) not in sys.path:
        sys.path.insert(0, str(resume_dir))

    try:
        from stack import read_entries, pop_entry
        from resume_exec import checkout_branches_typed, rebase_typed, reset_wip_typed

        stack_path = Path(ctx.workspace_path or ctx.project_path) / ".pause-stack"
        entries = read_entries(stack_path)

        if not entries:
            events.append(CommandFailed("resume", None, "empty_stack",
                                        "No paused branches on the stack", False))
            return events

        if branch:
            target = next((e for e in entries if e.branch == branch), None)
            if not target:
                events.append(CommandFailed("resume", None, "branch_not_found",
                                            f"Branch '{branch}' not on pause stack", False))
                return events
        else:
            target = entries[-1]

        # Checkout
        checkout = checkout_branches_typed(
            ctx.project_path,
            ctx.workspace_path or ctx.project_path,
            target.branch,
        )
        if not checkout.success:
            events.append(CommandFailed("resume", "checkout",
                                        checkout.error or "checkout_failed",
                                        checkout.error or "Failed to checkout branches",
                                        True))
            return events

        # Rebase
        rebase_result = rebase_typed(
            ctx.project_path,
            ctx.workspace_path or ctx.project_path,
            ctx.base_branch,
        )

        # Reset WIP
        reset_wip_typed(
            ctx.project_path,
            ctx.workspace_path or ctx.project_path,
        )

        # Pop from stack (only after all operations succeed)
        pop_entry(stack_path, target.branch)

        events.append(Resumed(target.branch, not rebase_result.skipped))

        new_entries = read_entries(stack_path)
        actions, suggested = derive_actions("active", len(new_entries), ctx.has_queue)
        events.append(StateChanged("idle", "active", actions, suggested))

    except Exception as e:
        events.append(CommandFailed("resume", None, "exception", str(e), True))

    return events
