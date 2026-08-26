#!/usr/bin/env python3
"""
wrap_orchestrator.py — Session wrap (handover) sequence orchestrator.

Uses the shared orchestrator engine from work-end/orchestrator_engine.py.
Only defines wrap-specific steps and context — no duplicated loop logic.

Usage:
    python3 handover/wrap_orchestrator.py \
        workspace=<path> project=<path> branch=<name> \
        [covers=<csv>] [issue_repo=<repo>] \
        [plan_path=<path>] [has_arc42=<yes|no>] [has_plan=<yes|no>] \
        [sweep_selected=<csv>] [skip_step=<name>] \
        [dry_run=yes]
"""

import sys
from dataclasses import dataclass
from pathlib import Path

_work_end = Path(__file__).resolve().parent.parent / "work-end"
sys.path.insert(0, str(_work_end))

from close_progress import read_close_progress, update_close_progress
from orchestrator_engine import run_loop, log_call

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None
from shared_steps import (
    StepDef,
    OrchestratorContextBase,
    WRAP_SWEEP_STEPS,
    sweep_defaults,
    make_forage_step,
    make_protocol_step,
    make_update_claude_md_step,
    make_write_content_step,
    make_garden_feedback_step,
    make_notes_step,
)


@dataclass
class WrapContext(OrchestratorContextBase):
    has_arc42: bool = False
    has_plan: bool = False


# --- Skip predicates (wrap-specific) ---

def _skip_no_arc42(ctx: WrapContext) -> bool:
    return not ctx.has_arc42


def _skip_no_plan(ctx: WrapContext) -> bool:
    return not ctx.has_plan


# --- Script builders (wrap-specific) ---

LOOSE_ENDS_SCRIPT = _work_end / "loose_ends_sweep.py"


def _loose_ends_script(ctx):
    return [sys.executable, str(LOOSE_ENDS_SCRIPT),
            f"workspace={ctx.workspace}", f"project={ctx.project}",
            f"branch={ctx.branch}"]


def _wip_commit_script(ctx):
    return [sys.executable, str(_work_end / "branch_cleanup.py"),
            "wip-commit", str(ctx.project), str(ctx.workspace)]


def _wrap_sweep_defaults() -> str:
    return sweep_defaults(WRAP_SWEEP_STEPS)


# --- Step sequence ---

WRAP_PHASE = "wrapping"

WRAP_USER_INPUT_STEPS = {
    "arc42_scan_wrap", "garden_feedback", "notes",
    "handoff_write", "epic_hygiene", "journal_entry",
}

WRAP_STEPS: list[StepDef] = [
    StepDef("loose_ends", WRAP_PHASE, "mechanical",
            script_fn=_loose_ends_script),
    StepDef("epic_hygiene", WRAP_PHASE, "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "epic_hygiene"}),
    StepDef("wrap_sweep_config", WRAP_PHASE, "judgment",
            action_context_fn=lambda ctx: {"ITEMS": _wrap_sweep_defaults()}),
    make_forage_step(WRAP_PHASE, "wrap_sweep_selected"),
    make_protocol_step(WRAP_PHASE, "wrap_sweep_selected"),
    make_update_claude_md_step(WRAP_PHASE, "wrap_sweep_selected"),
    StepDef("journal_entry", WRAP_PHASE, "judgment",
            skip_fn=_skip_no_plan,
            action_context_fn=lambda ctx: {"CONTEXT": "journal_entry"}),
    StepDef("arc42_scan_wrap", WRAP_PHASE, "judgment",
            skip_fn=_skip_no_arc42,
            action_context_fn=lambda ctx: {"CONTEXT": "arc42_scan"}),
    make_write_content_step(WRAP_PHASE, "wrap_sweep_selected"),
    make_garden_feedback_step(WRAP_PHASE),
    make_notes_step(WRAP_PHASE),
    StepDef("handoff_write", WRAP_PHASE, "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "handoff_write"}),
    StepDef("wip_commit", WRAP_PHASE, "mechanical",
            script_fn=_wip_commit_script),
]


# --- Orchestrator entry point ---

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
    covers = args.get("covers", "")
    issue_repo = args.get("issue_repo", "")
    dry_run = args.get("dry_run", "no") == "yes"
    plan_path = Path(args["plan_path"]) if args.get("plan_path") else None
    has_arc42 = args.get("has_arc42", "no") == "yes"
    has_plan = args.get("has_plan", "no") == "yes"

    if args.get("skip_step"):
        step = args["skip_step"]
        update_close_progress(workspace, step, "skipped")
        attempt_key = f"{step}_attempt"
        progress = read_close_progress(workspace)
        if attempt_key in progress:
            update_close_progress(workspace, attempt_key, "0")

    if args.get("step_done"):
        step = args["step_done"]
        update_close_progress(workspace, step, "done")
        if args.get("produced"):
            update_close_progress(workspace, f"{step}_produced", args["produced"])

    if args.get("sweep_selected") is not None:
        selected = args["sweep_selected"]
        update_close_progress(workspace, "wrap_sweep_config", "done")
        update_close_progress(workspace, "wrap_sweep_selected", selected)

    progress = read_close_progress(workspace)

    ctx = WrapContext(
        workspace=workspace, project=project, branch=branch,
        base_branch=base_branch, on_main=False, in_slot=False,
        covers=covers, issue_repo=issue_repo,
        progress=progress, dry_run=dry_run, call_log=[],
        plan_path=plan_path,
        has_arc42=has_arc42, has_plan=has_plan,
    )

    result = run_loop(
        WRAP_STEPS, ctx,
        user_input_steps=WRAP_USER_INPUT_STEPS,
        complete_summary="Wrap complete.",
    )
    log_call(workspace, "wrap", result, ctx.steps_executed, dry_run=dry_run)

    if result.get("ACTION") == "complete" and _wl and not dry_run:
        try:
            conn = _wl.connect()
            steps_data = _build_step_outcomes(ctx.progress)
            _wl.record_session_boundary(
                conn, mode="wrap", branch=branch,
                issue_repo=issue_repo,
                issue_number=int(covers.split(",")[0]) if covers else 0,
                steps=steps_data,
            )
            conn.close()
        except Exception:
            pass

    return result


def _build_step_outcomes(progress: dict[str, str]) -> dict:
    """Build step outcomes from progress for the session boundary event."""
    outcomes = {}
    for step_name in ["loose_ends", "forage", "protocol", "update_claude_md",
                      "write_content", "garden_feedback", "notes",
                      "epic_hygiene", "journal_entry", "arc42_scan_wrap",
                      "handoff_write", "wip_commit"]:
        status = progress.get(step_name)
        if status == "done":
            produced = int(progress.get(f"{step_name}_produced", "0"))
            outcomes[step_name] = {"ran": True, "produced": produced}
        elif status == "skipped":
            outcomes[step_name] = {"ran": False, "skipped": True}
    return outcomes


def main():
    args = parse_args(sys.argv[1:])
    required = ["workspace", "branch"]
    for key in required:
        if key not in args:
            print(f"ERROR=missing_arg ARG={key}")
            sys.exit(1)

    result = run_orchestrator(args)
    for k, v in result.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
