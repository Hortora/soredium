"""End command — mechanical close sequence."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from commands.events import (
    WorkEnded, StepProgress, StateChanged, CommandFailed,
)
from commands.registry import resolve_context, derive_actions


def execute(cwd: str | None = None, decide_fn: Callable | None = None,
            **_kwargs) -> list:
    """Run the mechanical close: promote, rebase, merge, push, stamp, cleanup."""
    events: list = []
    ctx = resolve_context(cwd)

    if ctx.state not in ("active", "closing:review", "closing:verified",
                         "closing:promoted", "closing:pushed",
                         "closing:merged", "closing:stamped"):
        events.append(CommandFailed("end", None, "wrong_state",
                                    f"Cannot end: state is '{ctx.state}'", False))
        return events

    end_dir = Path(__file__).parent.parent / "work-end"
    if str(end_dir) not in sys.path:
        sys.path.insert(0, str(end_dir))

    try:
        from work_end_execute import rebase_onto_base, merge_to_main, push_to_remote
        from branch_cleanup import cleanup as cleanup_fn

        # Step 1: Promote artifacts (skip LLM review/sweep)
        events.append(StepProgress("end", "promoting", None))
        try:
            from close_artifacts import close as close_artifacts
            close_result = close_artifacts(
                ctx.workspace_path or ctx.project_path,
                ctx.project_path,
                ctx.branch,
            )
        except Exception as e:
            events.append(StepProgress("end", "promoting", f"skipped: {e}"))

        # Step 2: Rebase
        events.append(StepProgress("end", "rebasing", None))
        rebase_result = rebase_onto_base(ctx.project_path, ctx.branch, ctx.base_branch)
        if not rebase_result.success:
            events.append(CommandFailed("end", "rebasing",
                                        "rebase_failed", rebase_result.error or "", True))
            return events

        # Step 3: Merge to main
        events.append(StepProgress("end", "merging", None))
        merge_result = merge_to_main(ctx.project_path, ctx.branch, ctx.base_branch)
        if not merge_result.success:
            events.append(CommandFailed("end", "merging",
                                        "merge_failed", merge_result.error or "", True))
            return events

        # Step 4: Push
        events.append(StepProgress("end", "pushing", None))
        push_result = push_to_remote(ctx.project_path, ctx.base_branch)
        if not push_result.success:
            events.append(CommandFailed("end", "pushing",
                                        "push_failed", push_result.error or "", True))
            return events

        # Step 5: Stamp
        events.append(StepProgress("end", "stamping", None))
        try:
            from land_branch import cmd_stamp
            stamp_exit = cmd_stamp(ctx.project_path, {
                "branch": ctx.branch,
                "base_branch": ctx.base_branch,
            })
        except Exception as e:
            events.append(StepProgress("end", "stamping", f"warning: {e}"))

        # Step 6: Cleanup
        events.append(StepProgress("end", "cleaning_up", None))

        issues_closed = [ctx.issue] if ctx.issue else []

        events.append(WorkEnded(ctx.branch, issues_closed))

        actions, suggested = derive_actions("idle", ctx.stack_depth)
        events.append(StateChanged("active", "idle", actions, suggested))

    except Exception as e:
        events.append(CommandFailed("end", None, "exception", str(e), True))

    return events
