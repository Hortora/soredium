"""Next command — advance plan to next issue."""
from __future__ import annotations

import sys
from pathlib import Path

from commands.events import PlanAdvanced, StateChanged, CommandFailed
from commands.registry import resolve_context, derive_actions


def execute(cwd: str | None = None, **_kwargs) -> list:
    """Advance plan to next issue."""
    events: list = []
    ctx = resolve_context(cwd)

    if ctx.state != "active":
        events.append(CommandFailed("next", None, "not_active",
                                    f"Cannot advance: state is '{ctx.state}', expected 'active'",
                                    False))
        return events

    if not ctx.has_plan:
        events.append(CommandFailed("next", None, "no_plan",
                                    "No .plan file found", False))
        return events

    slot_dir = Path(__file__).parent.parent / "work-slot"
    if str(slot_dir) not in sys.path:
        sys.path.insert(0, str(slot_dir))

    try:
        from plan_manager import parse_plan, advance, flatten

        workspace = Path(ctx.workspace_path) if ctx.workspace_path else Path(ctx.project_path)
        plan_path = workspace / "design" / ".plan"

        if not plan_path.exists():
            events.append(CommandFailed("next", None, "plan_not_found",
                                        f"Plan file not found at {plan_path}", False))
            return events

        tree = parse_plan(plan_path.read_text())
        leaves = flatten(tree)
        active = [l for l in leaves if l.active]

        if not active:
            events.append(CommandFailed("next", None, "no_active_issue",
                                        "No active issue in plan", False))
            return events

        completed_issue = active[0].issue_number
        result = advance(plan_path, tree)

        next_leaves = flatten(parse_plan(plan_path.read_text()))
        next_active = [l for l in next_leaves if l.active]
        remaining = [l for l in next_leaves if not l.completed]

        events.append(PlanAdvanced(
            completed_issue=completed_issue,
            next_issue=next_active[0].issue_number if next_active else None,
            next_title=next_active[0].title if next_active else None,
            position=f"{sum(1 for l in next_leaves if l.completed)}/{len(next_leaves)}",
            queue_complete=len(remaining) == 0,
        ))

        has_queue = len(remaining) > 0
        actions, suggested = derive_actions("active", ctx.stack_depth, has_queue)
        events.append(StateChanged("active", "active", actions, suggested))

    except Exception as e:
        events.append(CommandFailed("next", None, "exception", str(e), True))

    return events
