"""Quick-fix command — ephemeral branch landing."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from commands.events import QuickFixLanded, StateChanged, CommandFailed
from commands.registry import resolve_context, derive_actions


def execute(message: str = "", cwd: str | None = None,
            decide_fn: Callable | None = None, **_kwargs) -> list:
    """Land a quick fix on main via ephemeral branch."""
    events: list = []
    ctx = resolve_context(cwd)

    if not message:
        events.append(CommandFailed("quick-fix", None, "no_message",
                                    "Commit message required", True))
        return events

    if ctx.state != "idle":
        events.append(CommandFailed("quick-fix", None, "not_idle",
                                    f"Cannot quick-fix: state is '{ctx.state}', expected 'idle'",
                                    False))
        return events

    qf_dir = Path(__file__).parent.parent / "quick-fix"
    if str(qf_dir) not in sys.path:
        sys.path.insert(0, str(qf_dir))

    try:
        from quick_fix import run as qf_run
        exit_code = qf_run(ctx.project_path, message, ctx.base_branch)
        if exit_code != 0:
            events.append(CommandFailed("quick-fix", None, "run_failed",
                                        f"quick_fix.run() returned {exit_code}", True))
            return events

        events.append(QuickFixLanded(f"quick-fix", message))

        actions, suggested = derive_actions("idle", ctx.stack_depth)
        events.append(StateChanged("idle", "idle", actions, suggested))

    except Exception as e:
        events.append(CommandFailed("quick-fix", None, "exception", str(e), True))

    return events
