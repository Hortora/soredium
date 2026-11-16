"""Bidirectional chaining for work lifecycle commands.

Evaluates the current state and returns a directive telling the LLM
which action to take. All routing decisions are deterministic — the
LLM reads the directive and follows it, never decides routing itself.

Chain: continue <-> next <-> end <-> find
  ->  "nothing to do, cascade forward"
  <-  "not ready, go back"

Whether an item is finished is read from the queue (a done-not-closed marker),
not from GitHub: an issue stays open until the close ceremony has landed it, so
"still open" cannot mean "still being worked on".

Run as a script, it prints the directive for the skill to follow:

    work_chain.py <continue|next|end|sync|find> queue=<path> [issue_state=..] [on_main=yes]
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


def done_fields(queue) -> dict:
    """Queue items finished on a branch and awaiting the close ceremony."""
    items = queue.done_items() if queue else []
    return {
        "DONE_PENDING": str(len(items)),
        "DONE_ITEMS": ",".join(f"{i.ref}@{i.done_branch}" for i in items),
    }


def _done_pending(ctx: dict) -> int:
    value = str(ctx.get("DONE_PENDING", "") or "0")
    return int(value) if value.isdigit() else 0


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
    state = ctx.get("QUEUE_STATUS", "") or ctx.get("META_STATE", "")
    has_plan = ctx.get("HAS_QUEUE") == "yes" or ctx.get("HAS_PLAN") == "yes"
    active_issue = ctx.get("ACTIVE_ISSUE", "")
    position = ctx.get("PLAN_POSITION", "")
    on_main = ctx.get("ON_MAIN") == "yes"
    remaining = _parse_remaining(position)
    done = _done_pending(ctx)

    base = {
        "ACTIVE_ISSUE": active_issue,
        "ISSUE_STATE": issue_state or "",
        "QUEUE_REMAINING": str(remaining),
        "ON_MAIN": "yes" if on_main else "no",
        "DONE_PENDING": str(done),
    }

    if command == "continue":
        result = _evaluate_continue(state, has_plan, active_issue, issue_state, done)
    elif command == "next":
        result = _evaluate_next(state, has_plan, active_issue, issue_state, remaining, done)
    elif command == "end":
        result = _evaluate_end(state, has_plan, active_issue, issue_state, remaining, done)
    elif command == "sync":
        result = _evaluate_sync(state, has_plan, active_issue, on_main)
    elif command == "find":
        result = _evaluate_find(state, has_plan, active_issue, issue_state, done)
    else:
        result = {"DIRECTIVE": "proceed", "REASON": "unknown_command"}

    # Every time an item is finished, or finished items are waiting, the session must
    # weigh wrapping against carrying on. Emitted here so it does not depend on prose.
    finishing = command == "next" and result.get("REASON") in ("mark_done", "issue_complete")
    if done > 0 or finishing:
        result["OFFER"] = "wrap_or_continue"
    return {**base, **result}


def _evaluate_continue(
    state: str, has_plan: bool, active_issue: str, issue_state: str | None,
    done: int = 0,
) -> dict:
    if not active_issue and done > 0:
        return {"DIRECTIVE": "chain_to_end", "REASON": "done_items_await_close"}
    if state == "drained":
        return {"DIRECTIVE": "chain_to_next", "REASON": "queue_drained"}
    if not has_plan or not active_issue:
        return {"DIRECTIVE": "chain_to_next", "REASON": "no_active_work"}
    if issue_state == "CLOSED":
        return {"DIRECTIVE": "chain_to_next", "REASON": "active_issue_done"}
    return {"DIRECTIVE": "proceed", "REASON": "active_work_exists"}


def _evaluate_next(
    state: str, has_plan: bool, active_issue: str,
    issue_state: str | None, remaining: int, done: int = 0,
) -> dict:
    if not has_plan:
        return {"DIRECTIVE": "chain_to_end", "REASON": "no_plan"}
    if not active_issue:
        if done > 0:
            return {"DIRECTIVE": "chain_to_end", "REASON": "done_items_await_close"}
        return {"DIRECTIVE": "chain_to_end", "REASON": "queue_empty"}
    if issue_state == "CLOSED":
        return {"DIRECTIVE": "proceed", "REASON": "issue_complete"}
    # `work next` is the statement that the active item is finished. It is marked
    # done on its branch; the issue stays open until the close ceremony lands it.
    return {"DIRECTIVE": "proceed", "REASON": "mark_done"}


def _evaluate_end(
    state: str, has_plan: bool, active_issue: str,
    issue_state: str | None, remaining: int, done: int = 0,
) -> dict:
    # One ceremony closes every done item and the active one. An open issue is the
    # normal state before a close, never a reason to refuse it.
    if done > 0:
        return {"DIRECTIVE": "proceed", "REASON": "batch_close"}
    return {"DIRECTIVE": "proceed", "REASON": "ready_to_close"}


def _evaluate_sync(
    state: str, has_plan: bool, active_issue: str, on_main: bool,
) -> dict:
    if on_main:
        return {"DIRECTIVE": "chain_to_end", "REASON": "sync_requires_branch"}
    if state in ("drained", "paused", "idle"):
        return {"DIRECTIVE": "chain_to_end", "REASON": f"cannot_sync_from_{state}"}
    if not active_issue:
        return {"DIRECTIVE": "chain_to_end", "REASON": "no_active_work"}
    return {"DIRECTIVE": "proceed", "REASON": "ready_to_sync"}


def _evaluate_find(
    state: str, has_plan: bool, active_issue: str, issue_state: str | None,
    done: int = 0,
) -> dict:
    if not active_issue and done > 0:
        return {"DIRECTIVE": "chain_to_end", "REASON": "done_items_await_close"}
    if active_issue and issue_state in ("OPEN", "UNKNOWN"):
        return {"DIRECTIVE": "guard_next", "REASON": "unfinished_work"}
    return {"DIRECTIVE": "proceed", "REASON": "ready_to_find"}


COMMANDS = ("continue", "next", "end", "sync", "find")


def _context_from_queue(queue_path: Path, on_main: bool) -> dict:
    from queue_io import read_queue
    queue = read_queue(queue_path.parent) if queue_path.exists() else None
    if queue is None:
        return {"HAS_QUEUE": "no", "ON_MAIN": "yes" if on_main else "no"}
    active = queue.active_item()
    closed = sum(1 for i in queue.items if i.completed)
    return {
        "HAS_QUEUE": "yes",
        "QUEUE_STATUS": queue.state.status,
        "ACTIVE_ISSUE": active.ref if active else "",
        "PLAN_POSITION": f"{closed}/{len(queue.items)}",
        "ON_MAIN": "yes" if on_main else "no",
        **done_fields(queue),
    }


def _issue_state_for(active_issue: str) -> str:
    repo, _, number = active_issue.partition("#")
    if not repo or not number.isdigit():
        return "UNKNOWN"
    try:
        return _check_issue_state(IssueRef(repo, int(number)))
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(f"ERROR=unknown_command detail=expected one of {', '.join(COMMANDS)}")
        return 1
    opts = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
    if "queue" not in opts:
        print("ERROR=missing_queue detail=queue=<path to .queue> is required")
        return 1
    ctx = _context_from_queue(Path(opts["queue"]), opts.get("on_main") == "yes")
    issue_state = opts.get("issue_state")
    if issue_state is None and ctx.get("ACTIVE_ISSUE"):
        issue_state = _issue_state_for(ctx["ACTIVE_ISSUE"])
    result = evaluate(argv[1], ctx, issue_state=issue_state)
    print(f"CHAIN_DIRECTIVE={result.pop('DIRECTIVE')}")
    print(f"CHAIN_REASON={result.pop('REASON')}")
    if ctx.get("DONE_ITEMS"):
        result["DONE_ITEMS"] = ctx["DONE_ITEMS"]
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
