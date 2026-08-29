#!/usr/bin/env python3
"""
Shared orchestrator engine for close and wrap sequences.

Both work-end and wrap call `run_loop()` with their step list and context.
The engine owns: step iteration, progress tracking, mechanical execution,
judgment yielding, error retry. Orchestrator-specific behavior is injected
via callbacks.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from close_progress import update_close_progress
from shared_steps import StepDef, MAX_JUDGMENT_RETRIES


def run_script(cmd: list[str], workspace: Path,
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


def log_call(workspace: Path, mode: str, result: dict[str, str],
             steps_executed: list[str], dry_run: bool = False,
             extra: dict[str, str] | None = None) -> None:
    if dry_run:
        return
    log_file = ".close-log.jsonl" if mode == "close" else ".wrap-log.jsonl"
    log_path = workspace / log_file
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "action": result.get("ACTION", ""),
        "step": result.get("STEP", ""),
        "steps_executed": steps_executed,
        "error": result.get("ERROR", ""),
    }
    if extra:
        entry.update(extra)
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _yield_judgment(step_name: str, workspace: Path,
                    progress: dict[str, str],
                    context: dict[str, str]) -> dict[str, str]:
    attempt_key = f"{step_name}_attempt"
    attempt = int(progress.get(attempt_key, "0")) + 1

    if attempt > MAX_JUDGMENT_RETRIES:
        update_close_progress(workspace, "last_yielded", step_name)
        return {
            "ACTION": "user_input",
            "CONTEXT": "step_failed",
            "STEP": step_name,
            "ATTEMPTS": str(MAX_JUDGMENT_RETRIES),
            "REASON": f"Validation failed after {MAX_JUDGMENT_RETRIES} attempts",
        }

    update_close_progress(workspace, attempt_key, str(attempt))
    update_close_progress(workspace, "last_yielded", step_name)
    result = {"ACTION": step_name}
    result.update(context)
    return result


def _yield_user_input(step_name: str, workspace: Path,
                      progress: dict[str, str],
                      context: dict[str, str]) -> dict[str, str]:
    attempt_key = f"{step_name}_attempt"
    attempt = int(progress.get(attempt_key, "0")) + 1
    if attempt > MAX_JUDGMENT_RETRIES:
        update_close_progress(workspace, "last_yielded", step_name)
        return {
            "ACTION": "user_input",
            "CONTEXT": "step_failed",
            "STEP": step_name,
            "ATTEMPTS": str(MAX_JUDGMENT_RETRIES),
            "REASON": f"Validation failed after {MAX_JUDGMENT_RETRIES} attempts",
        }
    update_close_progress(workspace, attempt_key, str(attempt))
    update_close_progress(workspace, "last_yielded", step_name)
    return {"ACTION": "user_input", "STEP": step_name, **context}


def validate_skip(workspace: Path, step: str) -> dict[str, str] | None:
    """Validate skip_step against last_yielded. Returns error dict or None.

    last_yielded is NOT cleared here — the next yield overwrites it.
    This prevents the LLM from skipping multiple steps in sequence
    without the orchestrator yielding each one first.
    """
    from close_progress import read_close_progress
    progress = read_close_progress(workspace)
    last = progress.get("last_yielded", "")
    if last and step != last:
        return {
            "ACTION": "error",
            "ERROR": "invalid_skip",
            "STEP": step,
            "LAST_YIELDED": last,
            "REASON": f"Cannot skip '{step}' — only the last yielded step '{last}' can be skipped",
        }
    update_close_progress(workspace, step, "skipped")
    attempt_key = f"{step}_attempt"
    if attempt_key in progress:
        update_close_progress(workspace, attempt_key, "0")
    return None


def apply_step_done(workspace: Path, step: str, produced: str | None = None,
                    mechanical_steps: set[str] | None = None) -> dict[str, str] | None:
    """Mark a step done. Returns error dict if step is mechanical (not LLM-completable)."""
    if mechanical_steps and step in mechanical_steps:
        return {
            "ACTION": "error",
            "ERROR": "invalid_step_done",
            "STEP": step,
            "REASON": f"Cannot mark mechanical step '{step}' as done — only the orchestrator completes mechanical steps",
        }
    update_close_progress(workspace, step, "done")
    if produced:
        update_close_progress(workspace, f"{step}_produced", produced)


def _make_error_result(step_key: str, attempt: int,
                       result: dict[str, str]) -> dict[str, str]:
    if attempt >= 3:
        return {
            "ACTION": "user_input",
            "CONTEXT": "step_failed",
            "STEP": step_key,
            "ATTEMPTS": str(attempt),
            "REASON": result.get("ERROR", "unknown"),
            "ERROR_DETAIL": result.get("ERROR_DETAIL", ""),
        }
    return {"ACTION": "error", "STEP": step_key,
            "RETRY": str(attempt), **result}


def run_loop(
    steps: list[StepDef],
    ctx,
    *,
    execute_mechanical_fn: Callable | None = None,
    on_step_done: Callable | None = None,
    handle_lifecycle: Callable | None = None,
    per_repo_mechanical: Callable | None = None,
    per_repo_judgment: Callable | None = None,
    on_mechanical_error: Callable | None = None,
    user_input_steps: set[str] | None = None,
    complete_summary: str = "Complete.",
) -> dict[str, str]:
    """Run the orchestrator loop over a step list.

    Extension points:
    - execute_mechanical_fn(step, ctx) -> dict: override mechanical execution
      (for special cases like main-mode push, delete_progress). Return None
      to use default (script_fn).
    - on_step_done(step, ctx, result): called after each mechanical step
      completes successfully (for tracking landed_shas etc).
    - handle_lifecycle(step, ctx): handle lifecycle transitions (work-end only).
    - per_repo_mechanical(step, ctx) -> dict|None: handle per-repo fan-out
      for mechanical steps in slot mode. Return a result dict if handled,
      None to fall through to normal execution.
    - per_repo_judgment(step, ctx) -> dict|None: handle per-repo fan-out
      for judgment steps in slot mode.
    - on_mechanical_error(step, ctx, result) -> dict|None: classify mechanical
      errors. Return a result dict to override the generic retry path (e.g.
      for deterministic failures like rebase conflicts). Return None to fall
      through to the default retry/escalate logic.
    - user_input_steps: set of step names that yield via user_input
      (not regular judgment yield).
    """
    if user_input_steps is None:
        user_input_steps = set()

    for step in steps:
        if step.skip_fn and step.skip_fn(ctx):
            continue
        if ctx.done(step.name):
            continue

        if step.step_type == "mechanical":
            if per_repo_mechanical:
                handled = per_repo_mechanical(step, ctx)
                if handled is not None:
                    if handled:
                        return handled
                    continue

            attempt_key = f"{step.name}_mechanical_attempt"
            attempt = int(ctx.progress.get(attempt_key, "0"))

            if execute_mechanical_fn:
                result = execute_mechanical_fn(step, ctx)
            else:
                result = _default_execute_mechanical(step, ctx)

            if result and "ERROR" in result:
                if on_mechanical_error:
                    override = on_mechanical_error(step, ctx, result)
                    if override is not None:
                        ctx.steps_executed.append(f"{step.name}:ERROR:classified")
                        return override
                attempt += 1
                update_close_progress(ctx.workspace, attempt_key, str(attempt))
                ctx.steps_executed.append(f"{step.name}:ERROR:{attempt}")
                return _make_error_result(step.name, attempt, result)

            ctx.last_output = result or {}
            if on_step_done:
                on_step_done(step, ctx, result or {})
            update_close_progress(ctx.workspace, step.name, "done")
            ctx.steps_executed.append(step.name)
            continue

        if step.step_type == "judgment":
            if per_repo_judgment:
                handled = per_repo_judgment(step, ctx)
                if handled is not None:
                    if not handled:
                        update_close_progress(ctx.workspace, step.name, "done")
                        ctx.steps_executed.append(step.name)
                        continue
                    return handled

            context = step.action_context_fn(ctx) if step.action_context_fn else {}
            if step.name in user_input_steps:
                return _yield_user_input(step.name, ctx.workspace,
                                         ctx.progress, context)
            return _yield_judgment(step.name, ctx.workspace,
                                   ctx.progress, context)

        if step.step_type == "lifecycle":
            if handle_lifecycle:
                handle_lifecycle(step, ctx)
            update_close_progress(ctx.workspace, step.name, "done")
            ctx.steps_executed.append(step.name)
            continue

    return {"ACTION": "complete", "SUMMARY": complete_summary}


def _default_execute_mechanical(step: StepDef, ctx) -> dict[str, str]:
    if not step.script_fn:
        return {}
    cmd = step.script_fn(ctx)
    if cmd is None:
        return {}
    return run_script(cmd, ctx.workspace, dry_run=ctx.dry_run, call_log=ctx.call_log)
