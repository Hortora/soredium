"""Pause command — WIP commit + stack push."""
from __future__ import annotations

import sys
from pathlib import Path

from commands.events import WipCommitted, Paused, StateChanged, CommandFailed
from commands.registry import resolve_context, derive_actions


def execute(cwd: str | None = None, **_kwargs) -> list:
    """WIP commit both repos, push to pause stack, switch to main."""
    events: list = []
    ctx = resolve_context(cwd)

    if ctx.state != "active":
        events.append(CommandFailed("pause", None, "not_active",
                                    f"Cannot pause: state is '{ctx.state}', expected 'active'",
                                    False))
        return events

    pause_dir = Path(__file__).parent.parent / "work-pause"
    project_dir = Path(__file__).parent.parent / "project"
    if str(pause_dir) not in sys.path:
        sys.path.insert(0, str(pause_dir))
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))

    try:
        from pause_exec import commit_wip_typed
        from stack import StackEntry, push_entry

        message = f"WIP: pause {ctx.branch}"

        # WIP commit project
        proj_result = commit_wip_typed(ctx.project_path, message)
        if proj_result.error:
            events.append(CommandFailed("pause", "wip_commit_project",
                                        proj_result.error, proj_result.error, True))
            return events
        if proj_result.committed:
            events.append(WipCommitted(ctx.project_path, message))

        # WIP commit workspace
        ws_committed = False
        if ctx.workspace_path:
            ws_result = commit_wip_typed(ctx.workspace_path, message)
            ws_committed = ws_result.committed
            if ws_committed:
                events.append(WipCommitted(ctx.workspace_path, message))

        # Push to stack
        from datetime import datetime, timezone
        stack_path = Path(ctx.workspace_path or ctx.project_path) / ".pause-stack"
        entry = StackEntry(
            branch=ctx.branch,
            issue=ctx.issue or 0,
            paused=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            wip_project=proj_result.committed,
            wip_workspace=ws_committed,
        )
        depth = push_entry(stack_path, entry)

        events.append(Paused(ctx.branch, depth))

        actions, suggested = derive_actions("idle", depth)
        events.append(StateChanged("active", "idle", actions, suggested))

    except Exception as e:
        events.append(CommandFailed("pause", None, "exception", str(e), True))

    return events
