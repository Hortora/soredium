"""Status command — full context dump. Read-only."""
from __future__ import annotations

from commands.events import StatusReady
from commands.registry import resolve_context


def execute(cwd: str | None = None, **_kwargs) -> StatusReady:
    ctx = resolve_context(cwd)
    return StatusReady(
        branch=ctx.branch,
        state=ctx.state,
        on_main=ctx.on_main,
        in_slot=ctx.in_slot,
        has_plan=ctx.has_plan,
        plan_position=ctx.plan_position,
        stack_depth=ctx.stack_depth,
        owner_repo=ctx.owner_repo,
        base_branch=ctx.base_branch,
    )
