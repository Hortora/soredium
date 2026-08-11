"""Continue command — show context for resuming work. Read-only."""
from __future__ import annotations

import sys
from pathlib import Path

from commands.events import ContinueReady
from commands.registry import resolve_context


def execute(cwd: str | None = None, **_kwargs) -> ContinueReady:
    ctx = resolve_context(cwd)

    handoff_summary = None
    if ctx.workspace_path:
        handoff_path = Path(ctx.workspace_path) / "HANDOFF.md"
        if handoff_path.exists():
            try:
                text = handoff_path.read_text()
                lines = text.strip().splitlines()
                handoff_summary = "\n".join(lines[:20]) if lines else None
            except Exception:
                pass

    done_detected = False
    suggest_next = False
    suggest_end = False

    if ctx.has_plan and ctx.plan_position:
        parts = ctx.plan_position.split("/")
        if len(parts) == 2:
            try:
                current, total = int(parts[0]), int(parts[1])
                suggest_next = current < total
                suggest_end = current >= total
            except ValueError:
                pass

    return ContinueReady(
        issue=ctx.issue,
        branch=ctx.branch,
        state=ctx.state,
        handoff_summary=handoff_summary,
        done_detected=done_detected,
        suggest_next=suggest_next,
        suggest_end=suggest_end,
    )
