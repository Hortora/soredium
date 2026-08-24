#!/usr/bin/env python3
"""
work_end_orchestrator.py — Close sequence orchestrator.

Python drives, LLM assists. The LLM cannot skip what it cannot see.

Each invocation:
1. Reads META_STATE + .close-progress to determine position
2. Runs mechanical steps up to the next judgment point
3. Prints one ACTION= line with action-specific context
4. Exits

The LLM calls this script in a loop until ACTION=complete.

Usage:
    python3 work_end_orchestrator.py \
        workspace=<path> project=<path> branch=<name> \
        base_branch=<base> meta_state=<state> \
        [covers=<csv>] [issue_repo=<repo>] [in_slot=<yes|no>] \
        [slot_path=<path>] [on_main=<yes|no>] \
        [sweep_selected=<csv>] [skip_step=<name>] \
        [abort=yes] [conflict_resolved=yes]
"""
import sys
from pathlib import Path

from close_progress import (
    read_close_progress,
    update_close_progress,
    delete_close_progress,
    is_stale,
)

SWEEP_STEPS = ["forage", "protocol", "update_claude_md", "impl_doc_sync", "adr", "write_content"]

MAX_JUDGMENT_RETRIES = 3

ABORTABLE_STATES = {"closing:review", "closing:verified"}


def parse_args(argv: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for arg in argv:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k] = v
    return result


def run_orchestrator(args: dict[str, str]) -> dict[str, str]:
    workspace = Path(args["workspace"])
    project = Path(args.get("project", ""))
    branch = args.get("branch", "")
    base_branch = args.get("base_branch", "main")
    meta_state = args.get("meta_state", "closing:review")
    on_main = args.get("on_main", "no") == "yes"
    in_slot = args.get("in_slot", "no") == "yes"
    covers = args.get("covers", "")
    issue_repo = args.get("issue_repo", "")

    if args.get("abort") == "yes":
        return _handle_abort(workspace, meta_state)

    if args.get("skip_step"):
        step = args["skip_step"]
        update_close_progress(workspace, step, "skipped")
        attempt_key = f"{step}_attempt"
        progress = read_close_progress(workspace)
        if attempt_key in progress:
            update_close_progress(workspace, attempt_key, "0")

    if args.get("sweep_selected") is not None and "sweep_config" in read_close_progress(workspace):
        selected = args["sweep_selected"]
        update_close_progress(workspace, "sweep_selected", selected)

    progress = read_close_progress(workspace)

    if is_stale(progress, meta_state):
        delete_close_progress(workspace)
        progress = {}

    return _next_action(workspace, project, branch, base_branch,
                        meta_state, on_main, in_slot, covers, issue_repo,
                        progress)


def _handle_abort(workspace: Path, meta_state: str) -> dict[str, str]:
    if meta_state in ABORTABLE_STATES:
        delete_close_progress(workspace)
        return {
            "ACTION": "complete",
            "SUMMARY": "Aborted — returned to active state",
        }
    return {
        "ACTION": "error",
        "ERROR": "abort_blocked",
        "STATE": meta_state,
        "REASON": "Post-promotion states are forward-only",
    }


def _next_action(workspace: Path, project: Path, branch: str,
                 base_branch: str, meta_state: str, on_main: bool,
                 in_slot: bool, covers: str, issue_repo: str,
                 progress: dict[str, str]) -> dict[str, str]:

    def done(step: str) -> bool:
        return progress.get(step) in ("done", "skipped")

    # --- Phase: closing:review ---

    if not done("review"):
        return _yield_judgment("review", workspace, progress, {
            "DIFF_RANGE": f"{base_branch}..{branch}",
        })

    if not done("sweep_config"):
        return {"ACTION": "sweep_config", "ITEMS": _sweep_defaults()}

    selected = _get_sweep_selected(progress)
    for step in SWEEP_STEPS:
        if step in selected and not done(step):
            return _yield_judgment(step, workspace, progress, {})

    # --- Phase: closing:promoted ---

    if not done("trajectory"):
        return _yield_judgment("trajectory", workspace, progress, {})

    if not on_main and not done("rebase"):
        update_close_progress(workspace, "rebase", "done")

    if not on_main and not done("squash"):
        return _yield_judgment("squash", workspace, progress, {
            "REPOS": project.name,
        })

    if not done("land"):
        update_close_progress(workspace, "land", "done")

    # --- Phase: closing:stamped ---

    if not done("close_issues") and covers:
        update_close_progress(workspace, "close_issues", "done")

    if not done("verify"):
        update_close_progress(workspace, "verify", "done")

    cleanup_steps = ["arc42_scan", "session_rename", "garden_feedback", "notes"]
    for step in cleanup_steps:
        if not done(step):
            ctx = step
            return {
                "ACTION": "user_input",
                "CONTEXT": ctx,
            }

    if not done("cleanup"):
        update_close_progress(workspace, "cleanup", "done")

    return {
        "ACTION": "complete",
        "SUMMARY": "Close complete.",
    }


def _yield_judgment(step: str, workspace: Path,
                    progress: dict[str, str],
                    context: dict[str, str]) -> dict[str, str]:
    attempt_key = f"{step}_attempt"
    attempt = int(progress.get(attempt_key, "0")) + 1

    if attempt > MAX_JUDGMENT_RETRIES:
        return {
            "ACTION": "user_input",
            "CONTEXT": "step_failed",
            "STEP": step,
            "ATTEMPTS": str(MAX_JUDGMENT_RETRIES),
            "REASON": f"Validation failed after {MAX_JUDGMENT_RETRIES} attempts",
        }

    update_close_progress(workspace, attempt_key, str(attempt))
    result = {"ACTION": step}
    result.update(context)
    return result


def _sweep_defaults() -> str:
    return ",".join(f"{s}:on" for s in SWEEP_STEPS)


def _get_sweep_selected(progress: dict[str, str]) -> set[str]:
    raw = progress.get("sweep_selected", "")
    if not raw:
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}


def main():
    args = parse_args(sys.argv[1:])
    required = ["workspace", "branch", "meta_state"]
    for key in required:
        if key not in args:
            print(f"ERROR=missing_arg ARG={key}")
            sys.exit(1)

    result = run_orchestrator(args)
    for k, v in result.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
