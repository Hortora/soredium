"""Brief command — context summary. Read-only, no state change."""
from __future__ import annotations

import sys
from pathlib import Path

from commands.events import BriefReady, HealthCheck
from commands.registry import resolve_context


def execute(cwd: str | None = None, **_kwargs) -> BriefReady:
    """Run brief — context summary."""
    project_dir = Path(__file__).parent.parent / "project"
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))

    ctx = resolve_context(cwd)

    health: list[HealthCheck] = []
    try:
        from work_health import run_checks
        raw_checks = run_checks(
            "branch", ctx.project_path,
            ctx.workspace_path or "", ctx.branch, ctx.owner_repo,
        )
        if raw_checks:
            for c in raw_checks:
                if isinstance(c, dict):
                    health.append(HealthCheck(
                        c.get("check", ""),
                        c.get("status", "ok"),
                        c.get("detail"),
                    ))
    except Exception:
        pass

    return BriefReady(
        issue=ctx.issue,
        branch=ctx.branch,
        state=ctx.state,
        queue_position=ctx.plan_position,
        health=health,
        is_epic=ctx.is_epic,
        epic_batch=ctx.epic_batch,
        epic_active_issue=ctx.epic_active_issue,
    )
