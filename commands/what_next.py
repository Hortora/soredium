"""What-next command — enrichment recommendations. Read-only."""
from __future__ import annotations

import sys
from pathlib import Path

from commands.events import WhatNextReady, Recommendation
from commands.registry import resolve_context


def execute(cwd: str | None = None, **_kwargs) -> WhatNextReady:
    ctx = resolve_context(cwd)
    repo = ctx.owner_repo or ""

    if not repo:
        return WhatNextReady(recommendations=[])

    scripts_dir = Path(__file__).parent.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    try:
        from enrichment import what_next_typed
        items = what_next_typed(repo)
        return WhatNextReady(recommendations=[
            Recommendation(
                issue=item.issue_number,
                title=item.title,
                strategic_role=item.strategic_role,
                readiness=item.readiness,
                reason=item.reason,
            )
            for item in items
        ])
    except Exception:
        return WhatNextReady(recommendations=[])
