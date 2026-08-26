#!/usr/bin/env python3
"""
wrap_orchestrator.py — Session wrap (handover) sequence orchestrator.

Same yield-based pattern as work_end_orchestrator.py. Python drives,
LLM assists. Each invocation runs mechanical steps up to the next
judgment point, prints one ACTION= line, and exits.

Shared step definitions imported from work-end/shared_steps.py.

Usage:
    python3 handover/wrap_orchestrator.py \
        workspace=<path> project=<path> branch=<name> \
        [covers=<csv>] [issue_repo=<repo>] \
        [plan_path=<path>] [has_arc42=<yes|no>] [has_plan=<yes|no>] \
        [sweep_selected=<csv>] [skip_step=<name>] \
        [dry_run=yes]
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_work_end = Path(__file__).resolve().parent.parent / "work-end"
sys.path.insert(0, str(_work_end))

from close_progress import (
    read_close_progress,
    update_close_progress,
    write_close_progress,
    delete_close_progress,
)
from shared_steps import (
    StepDef,
    OrchestratorContextBase,
    WRAP_SWEEP_STEPS,
    MAX_JUDGMENT_RETRIES,
    JUDGMENT_STEPS_SET,
    _is_sweep_deselected,
    sweep_defaults,
    get_sweep_selected,
    yield_judgment,
    yield_user_input,
    make_forage_step,
    make_protocol_step,
    make_update_claude_md_step,
    make_write_content_step,
    make_arc42_scan_step,
    make_session_rename_step,
    make_garden_feedback_step,
    make_notes_step,
)

WRAP_LOG_FILE = ".wrap-log.jsonl"
WRAP_PROGRESS_FILE = ".close-progress"


@dataclass
class WrapContext(OrchestratorContextBase):
    has_arc42: bool = False
    has_plan: bool = False


def _skip_no_arc42(ctx: WrapContext) -> bool:
    return not ctx.has_arc42


def _skip_no_plan(ctx: WrapContext) -> bool:
    return not ctx.has_plan


def _run_script(cmd: list[str], workspace: Path,
                dry_run: bool = False,
                call_log: list | None = None) -> dict[str, str]:
    if dry_run:
        if call_log is not None:
            call_log.append(cmd)
        return {}
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(workspace),
        )
        result: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
        if proc.returncode != 0 and "ERROR" not in result:
            result["ERROR"] = f"exit_{proc.returncode}"
            if proc.stderr:
                result["STDERR"] = proc.stderr[:500]
        return result
    except subprocess.TimeoutExpired:
        return {"ERROR": "timeout"}
    except FileNotFoundError:
        return {"ERROR": f"script_not_found: {cmd[0]}"}


def _log_call(workspace: Path, result: dict[str, str],
              steps_executed: list[str], dry_run: bool = False) -> None:
    if dry_run:
        return
    log_path = workspace / WRAP_LOG_FILE
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "wrap",
        "action": result.get("ACTION", ""),
        "step": result.get("STEP", ""),
        "steps_executed": steps_executed,
        "error": result.get("ERROR", ""),
    }
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


LOOSE_ENDS_SCRIPT = _work_end / "loose_ends_sweep.py"
HYGIENE_SCRIPT = _work_end / "hygiene_scan.py"


def _loose_ends_script(ctx):
    return [sys.executable, str(LOOSE_ENDS_SCRIPT),
            f"workspace={ctx.workspace}", f"project={ctx.project}",
            f"branch={ctx.branch}"]


def _hygiene_script(ctx):
    cmd = [sys.executable, str(HYGIENE_SCRIPT),
           f"workspace={ctx.workspace}", f"project={ctx.project}"]
    if ctx.plan_path:
        cmd.append(f"plan_path={ctx.plan_path}")
    return cmd


def _wip_commit_script(ctx):
    return [sys.executable, str(_work_end / "branch_cleanup.py"),
            "wip-commit", str(ctx.project), str(ctx.workspace)]


def _wrap_sweep_defaults() -> str:
    return sweep_defaults(WRAP_SWEEP_STEPS)


WRAP_PHASE = "wrapping"

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

    result = _next_action(ctx)
    _log_call(workspace, result, ctx.steps_executed, dry_run=dry_run)
    return result


def _next_action(ctx: WrapContext) -> dict[str, str]:
    for step in WRAP_STEPS:
        if step.skip_fn and step.skip_fn(ctx):
            continue
        if ctx.done(step.name):
            continue

        if step.step_type == "mechanical":
            result = _execute_mechanical(step, ctx)
            if result and "ERROR" in result:
                attempt_key = f"{step.name}_mechanical_attempt"
                attempt = int(ctx.progress.get(attempt_key, "0")) + 1
                update_close_progress(ctx.workspace, attempt_key, str(attempt))
                ctx.steps_executed.append(f"{step.name}:ERROR:{attempt}")
                if attempt >= 3:
                    return {
                        "ACTION": "user_input",
                        "CONTEXT": "step_failed",
                        "STEP": step.name,
                        "ATTEMPTS": str(attempt),
                        "REASON": result.get("ERROR", "unknown"),
                    }
                return {"ACTION": "error", "STEP": step.name,
                        "RETRY": str(attempt), **result}
            ctx.last_output = result or {}
            update_close_progress(ctx.workspace, step.name, "done")
            ctx.steps_executed.append(step.name)
            continue

        if step.step_type == "judgment":
            if step.name in ("arc42_scan_wrap", "session_rename",
                             "garden_feedback", "notes", "handoff_write",
                             "epic_hygiene", "journal_entry"):
                return yield_user_input(step.name, ctx,
                                        step.action_context_fn(ctx) if step.action_context_fn else {})
            return yield_judgment(step.name, ctx.workspace, ctx.progress,
                                 step.action_context_fn(ctx) if step.action_context_fn else {})

    return {"ACTION": "complete", "SUMMARY": "Wrap complete."}


def _execute_mechanical(step: StepDef, ctx: WrapContext) -> dict[str, str]:
    if not step.script_fn:
        return {}
    cmd = step.script_fn(ctx)
    if cmd is None:
        return {}
    return _run_script(cmd, ctx.workspace, dry_run=ctx.dry_run, call_log=ctx.call_log)


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
