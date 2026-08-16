"""Command registry — action derivation, context resolution, state refresh."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from commands.events import StateChanged


# ---------------------------------------------------------------------------
# Action derivation table
# ---------------------------------------------------------------------------

_ACTION_TABLE: dict[str, dict] = {
    "idle": {
        "actions": ["start", "quick-fix", "what-next", "status"],
        "suggested": "start",
        "with_stack": {
            "actions": ["start", "quick-fix", "resume", "what-next", "status"],
            "suggested": "resume",
        },
    },
    "active": {
        "actions": ["continue", "brief", "next", "pause", "end", "session", "status"],
        "suggested": "next",
        "no_queue": {
            "actions": ["continue", "brief", "pause", "end", "session", "status"],
            "suggested": "end",
        },
    },
    "paused": {
        "actions": ["resume", "start", "what-next", "status"],
        "suggested": "resume",
    },
    "closing:review": {"actions": ["abort", "status"], "suggested": "abort"},
    "closing:verified": {"actions": ["abort", "status"], "suggested": "abort"},
    "closing:promoted": {"actions": ["status"], "suggested": None},
    "closing:pushed": {"actions": ["status"], "suggested": None},
    "closing:merged": {"actions": ["status"], "suggested": None},
    "closing:stamped": {"actions": ["status"], "suggested": None},
}


def derive_actions(state: str, stack_depth: int = 0,
                   has_queue: bool = True) -> tuple[list[str], str | None]:
    """Derive available actions and suggested action from lifecycle state."""
    entry = _ACTION_TABLE.get(state, {"actions": ["status"], "suggested": None})

    if state == "idle" and stack_depth > 0 and "with_stack" in entry:
        entry = entry["with_stack"]
    elif state == "active" and not has_queue and "no_queue" in entry:
        entry = entry["no_queue"]

    return list(entry["actions"]), entry.get("suggested")


# ---------------------------------------------------------------------------
# Context resolution
# ---------------------------------------------------------------------------

@dataclass
class Context:
    project_path: str
    workspace_path: str | None
    branch: str
    state: str
    on_main: bool
    in_slot: bool
    has_plan: bool
    plan_position: str | None
    stack_depth: int
    owner_repo: str | None
    base_branch: str
    meta_path: str | None
    has_queue: bool
    issue: int | None
    is_epic: bool
    epic_batch: str | None
    epic_active_issue: int | None


def resolve_context(cwd: str | None = None) -> Context:
    """Resolve full context from topology + work_state + ctx."""
    project_dir = Path(__file__).parent.parent / "project"
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    from ctx import resolve as ctx_resolve

    raw = ctx_resolve(cwd=cwd)

    plan_pos = raw.get("PLAN_POSITION") or None
    has_queue = False
    if plan_pos:
        parts = plan_pos.split("/")
        if len(parts) == 2:
            try:
                current, total = int(parts[0]), int(parts[1])
                has_queue = current < total
            except ValueError:
                pass

    issue_str = raw.get("ISSUE_N") or raw.get("PLAN_ACTIVE_ISSUE") or ""
    issue = int(issue_str) if issue_str.isdigit() else None

    workspace = raw.get("WORKSPACE") or None
    meta_path = None
    if workspace:
        candidate = Path(workspace) / ".plan"
        if candidate.exists():
            meta_path = str(candidate)

    return Context(
        project_path=raw.get("PROJECT", ""),
        workspace_path=workspace,
        branch=raw.get("CURRENT_BRANCH", "main"),
        state=raw.get("META_STATE", "") or "idle",
        on_main=raw.get("ON_MAIN") == "yes",
        in_slot=raw.get("IN_SLOT") == "yes",
        has_plan=raw.get("HAS_PLAN") == "yes",
        plan_position=plan_pos,
        stack_depth=int(raw.get("STACK_DEPTH", "0")),
        owner_repo=raw.get("OWNER_REPO") or None,
        base_branch=raw.get("BASE_BRANCH", "main"),
        meta_path=meta_path,
        has_queue=has_queue,
        issue=issue,
        is_epic=raw.get("IS_EPIC") == "yes",
        epic_batch=raw.get("EPIC_BATCH") or None,
        epic_active_issue=int(raw["EPIC_ACTIVE_ISSUE"]) if raw.get("EPIC_ACTIVE_ISSUE", "").isdigit() else None,
    )


def refresh(cwd: str | None = None) -> StateChanged:
    """Re-detect state and return a StateChanged event."""
    ctx = resolve_context(cwd)
    actions, suggested = derive_actions(ctx.state, ctx.stack_depth, ctx.has_queue)
    return StateChanged(ctx.state, ctx.state, actions, suggested)
