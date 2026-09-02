"""Bidirectional chaining for work lifecycle commands.

Evaluates the current state and returns a directive telling the LLM
which action to take. All routing decisions are deterministic — the
LLM reads the directive and follows it, never decides routing itself.

Chain: continue <-> next <-> end <-> find
  ->  "nothing to do, cascade forward"
  <-  "not ready, go back"
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))
from plan_manager import IssueRef


def _check_issue_state(ref: IssueRef) -> str:
    if not ref:
        return "UNKNOWN"
    result = subprocess.run(
        ["gh", "issue", "view", str(ref.number), "--repo", ref.repo,
         "--json", "state", "--jq", ".state"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"


def _parse_remaining(position: str) -> int:
    if not position or "/" not in position:
        return 0
    parts = position.split("/")
    try:
        completed, total = int(parts[0]), int(parts[1])
        return max(0, total - completed)
    except (ValueError, IndexError):
        return 0


def evaluate(
    command: str,
    ctx: dict,
    issue_state: str | None = None,
) -> dict:
    state = ctx.get("META_STATE", "")
    has_plan = ctx.get("HAS_PLAN") == "yes"
    active_issue = ctx.get("ACTIVE_ISSUE", "")
    position = ctx.get("PLAN_POSITION", "")
    on_main = ctx.get("ON_MAIN") == "yes"
    remaining = _parse_remaining(position)

    base = {
        "ACTIVE_ISSUE": active_issue,
        "ISSUE_STATE": issue_state or "",
        "QUEUE_REMAINING": str(remaining),
        "ON_MAIN": "yes" if on_main else "no",
    }

    if command == "continue":
        return {**base, **_evaluate_continue(state, has_plan, active_issue, issue_state)}
    elif command == "next":
        return {**base, **_evaluate_next(state, has_plan, active_issue, issue_state, remaining)}
    elif command == "end":
        return {**base, **_evaluate_end(state, has_plan, active_issue, issue_state, remaining)}
    elif command == "find":
        return {**base, **_evaluate_find(state, has_plan, active_issue, issue_state)}
    else:
        return {**base, "DIRECTIVE": "proceed", "REASON": "unknown_command"}


def _evaluate_continue(
    state: str, has_plan: bool, active_issue: str, issue_state: str | None,
) -> dict:
    if state == "drained":
        return {"DIRECTIVE": "chain_to_next", "REASON": "queue_drained"}
    if not has_plan or not active_issue:
        return {"DIRECTIVE": "chain_to_next", "REASON": "no_active_work"}
    if issue_state == "CLOSED":
        return {"DIRECTIVE": "chain_to_next", "REASON": "active_issue_done"}
    return {"DIRECTIVE": "proceed", "REASON": "active_work_exists"}


def _evaluate_next(
    state: str, has_plan: bool, active_issue: str,
    issue_state: str | None, remaining: int,
) -> dict:
    if not has_plan:
        return {"DIRECTIVE": "chain_to_end", "REASON": "no_plan"}
    if not active_issue:
        return {"DIRECTIVE": "chain_to_end", "REASON": "queue_empty"}
    if issue_state == "OPEN":
        return {"DIRECTIVE": "guard_continue", "REASON": "issue_still_open"}
    return {"DIRECTIVE": "proceed", "REASON": "issue_complete"}


def _evaluate_end(
    state: str, has_plan: bool, active_issue: str,
    issue_state: str | None, remaining: int,
) -> dict:
    if has_plan and active_issue and issue_state == "OPEN":
        return {"DIRECTIVE": "guard_next", "REASON": "queue_not_empty"}
    return {"DIRECTIVE": "proceed", "REASON": "ready_to_close"}


def _evaluate_find(
    state: str, has_plan: bool, active_issue: str, issue_state: str | None,
) -> dict:
    if active_issue and issue_state in ("OPEN", "UNKNOWN"):
        return {"DIRECTIVE": "guard_next", "REASON": "unfinished_work"}
    return {"DIRECTIVE": "proceed", "REASON": "ready_to_find"}
