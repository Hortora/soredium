#!/usr/bin/env python3
"""
Shared orchestrator engine for lifecycle commands.

All lifecycle orchestrators call `run_loop()` with their step list and
context. The engine owns: step iteration, progress tracking, mechanical
execution, judgment yielding, error retry. Orchestrator-specific behavior
is injected via callbacks.

Moved from work-end/ to project/ for shared access (#384).
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from work_progress import update_progress as update_close_progress
from shared_steps import StepDef, MAX_JUDGMENT_RETRIES, MAX_MECHANICAL_RETRIES

_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from verification.outcomes import VerifyResult


def validate_requires(steps: list[StepDef]) -> None:
    step_names = {s.name for s in steps}
    for step in steps:
        for req in step.requires:
            if req == step.name:
                raise ValueError(
                    f"Step '{step.name}' requires itself"
                )
            if req not in step_names:
                raise ValueError(
                    f"Step '{step.name}' requires '{req}' which does not exist"
                )


def _per_repo_done(ctx, step_name: str) -> bool:
    """Check if a step completed via per-repo fan-out (step:repo keys)."""
    return ctx.progress.is_per_repo_done(step_name)


def _mark_done(ctx, step_name: str, status: str = "done") -> None:
    update_close_progress(ctx.workspace, step_name, status)
    ctx.progress[step_name] = status


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
                    progress,
                    context: dict[str, str]) -> dict[str, str]:
    attempt = progress.get_attempt(step_name) + 1

    if attempt > MAX_JUDGMENT_RETRIES:
        update_close_progress(workspace, "last_yielded", step_name)
        return {
            "ACTION": "user_input",
            "CONTEXT": "step_failed",
            "STEP": step_name,
            "ATTEMPTS": str(MAX_JUDGMENT_RETRIES),
            "REASON": f"Validation failed after {MAX_JUDGMENT_RETRIES} attempts",
        }

    update_close_progress(workspace, f"{step_name}_attempt", str(attempt))
    update_close_progress(workspace, "last_yielded", step_name)
    result = {"ACTION": step_name,
              "COMPLETE_WITH": f"step_done={step_name} produced=N"}
    result.update(context)
    return result


def _yield_user_input(step_name: str, workspace: Path,
                      progress,
                      context: dict[str, str]) -> dict[str, str]:
    attempt = progress.get_attempt(step_name) + 1
    if attempt > MAX_JUDGMENT_RETRIES:
        update_close_progress(workspace, "last_yielded", step_name)
        return {
            "ACTION": "user_input",
            "CONTEXT": "step_failed",
            "STEP": step_name,
            "ATTEMPTS": str(MAX_JUDGMENT_RETRIES),
            "REASON": f"Validation failed after {MAX_JUDGMENT_RETRIES} attempts",
        }
    update_close_progress(workspace, f"{step_name}_attempt", str(attempt))
    update_close_progress(workspace, "last_yielded", step_name)
    return {"ACTION": "user_input", "STEP": step_name,
            "COMPLETE_WITH": f"step_done={step_name}", **context}


def validate_skip(workspace: Path, step: str) -> dict[str, str] | None:
    """Validate skip_step against last_yielded. Returns error dict or None.

    last_yielded is NOT cleared here — the next yield overwrites it.
    This prevents the LLM from skipping multiple steps in sequence
    without the orchestrator yielding each one first.
    """
    from work_progress import read_progress as read_close_progress
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


def _yield_unknown_escalation(step_name: str, verification) -> dict[str, str]:
    return {
        "ACTION": "user_input",
        "CONTEXT": "unknown_verification",
        "STEP": step_name,
        "CHECK": verification.check,
        "RESULT": "unknown",
        "EVIDENCE": json.dumps(verification.evidence),
        "REASON": f"Verification '{verification.check}' returned UNKNOWN "
                  f"after {MAX_MECHANICAL_RETRIES} retries",
    }


def _make_verify_fail_result(step_name: str, attempt: int,
                              verification) -> dict[str, str]:
    return {
        "ACTION": "error",
        "ERROR": "verify_failed",
        "STEP": step_name,
        "RETRY": str(attempt),
        "CHECK": verification.check,
        "EVIDENCE": json.dumps(verification.evidence),
        "REASON": f"Verification '{verification.check}' returned FAIL",
    }


def _make_unknown_retry_result(step_name: str, attempt: int,
                                verification) -> dict[str, str]:
    return {
        "ACTION": "error",
        "ERROR": "unknown_verification",
        "STEP": step_name,
        "RETRY": str(attempt),
        "CHECK": verification.check,
        "EVIDENCE": json.dumps(verification.evidence),
        "REASON": f"Verification '{verification.check}' returned UNKNOWN — retrying",
    }


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
    final_gate_fn: Callable | None = None,
) -> dict[str, str]:
    """Run the orchestrator loop over a step list.

    Extension points:
    - execute_mechanical_fn(step, ctx) -> dict: override mechanical execution
    - on_step_done(step, ctx, result): called after each mechanical step
    - handle_lifecycle(step, ctx): handle lifecycle transitions
    - per_repo_mechanical(step, ctx) -> dict|None: per-repo fan-out (mechanical)
    - per_repo_judgment(step, ctx) -> dict|None: per-repo fan-out (judgment)
    - on_mechanical_error(step, ctx, result) -> dict|None: classify errors
    - user_input_steps: steps that yield via user_input
    - final_gate_fn(ctx) -> dict|None: inescapable gate before complete
    """
    if user_input_steps is None:
        user_input_steps = set()

    pipeline_mode = getattr(ctx, "pipeline_mode", None)
    if pipeline_mode is not None:
        steps = [s for s in steps if pipeline_mode in s.modes]

    active_step_names = {s.name for s in steps}
    step_by_name = {s.name: s for s in steps}

    from shared_steps import ALL_DISPOSITIONS
    for step in steps:
        if step.dispositions != ALL_DISPOSITIONS and hasattr(ctx, 'repos') and ctx.repos:
            has_matching = any(
                r.state.disposition in step.dispositions
                for r in ctx.repos
                if r.state.repo_type in step.disposition_repo_types
            )
            if not has_matching:
                _mark_done(ctx, step.name, "skipped")
                ctx.steps_executed.append(f"{step.name}:disposition_skip")
                continue

        if step.skip_fn and step.skip_fn(ctx):
            continue

        if step.requires:
            unmet = [r for r in step.requires
                     if r in active_step_names
                     and not ctx.done(r)
                     and not _per_repo_done(ctx, r)
                     and not (r in step_by_name
                              and step_by_name[r].skip_fn
                              and step_by_name[r].skip_fn(ctx))]
            if unmet:
                return {
                    "ACTION": "error",
                    "ERROR": "unmet_dependency",
                    "STEP": step.name,
                    "REASON": f"Step '{step.name}' requires {unmet} to complete first",
                }

        if step.step_type == "mechanical":
            if per_repo_mechanical:
                handled = per_repo_mechanical(step, ctx)
                if handled is not None:
                    if handled:
                        return handled
                    continue

            if ctx.done(step.name):
                continue

            attempt_key = f"{step.name}_mechanical_attempt"
            raw = ctx.progress.get(attempt_key, "0")
            try:
                attempt = int(raw)
            except (ValueError, TypeError):
                attempt = 0

            if attempt >= MAX_MECHANICAL_RETRIES:
                attempt = 0
                update_close_progress(ctx.workspace, attempt_key, "0")

            if step.outcome_fn:
                v = step.outcome_fn(ctx)
                if v.result == VerifyResult.PASS:
                    _mark_done(ctx, step.name)
                    ctx.steps_executed.append(f"{step.name}:verify_skip")
                    continue
                if v.result == VerifyResult.UNKNOWN:
                    if attempt > 0:
                        attempt += 1
                        update_close_progress(ctx.workspace, attempt_key, str(attempt))
                        if attempt >= MAX_MECHANICAL_RETRIES:
                            return _yield_unknown_escalation(step.name, v)
                        if not step.idempotent:
                            return _make_unknown_retry_result(step.name, attempt, v)

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
                if attempt >= MAX_MECHANICAL_RETRIES:
                    _mark_done(ctx, step.name, "skipped_error")
                    ctx.steps_executed.append(f"{step.name}:SKIPPED_ERROR")
                    continue
                ctx.steps_executed.append(f"{step.name}:ERROR:{attempt}")
                return _make_error_result(step.name, attempt, result)

            ctx.last_output = result or {}
            if on_step_done:
                on_step_done(step, ctx, result or {})

            if step.outcome_fn:
                v = step.outcome_fn(ctx)
                if v.result == VerifyResult.PASS:
                    _mark_done(ctx, step.name)
                    ctx.steps_executed.append(step.name)
                    continue
                if v.result == VerifyResult.FAIL:
                    attempt += 1
                    update_close_progress(ctx.workspace, attempt_key, str(attempt))
                    if attempt >= MAX_MECHANICAL_RETRIES:
                        _mark_done(ctx, step.name, "skipped_error")
                        ctx.steps_executed.append(f"{step.name}:VERIFY_FAIL:skipped")
                        continue
                    return _make_verify_fail_result(step.name, attempt, v)
                if v.result == VerifyResult.UNKNOWN:
                    attempt += 1
                    update_close_progress(ctx.workspace, attempt_key, str(attempt))
                    if attempt >= MAX_MECHANICAL_RETRIES:
                        return _yield_unknown_escalation(step.name, v)
                    return _make_unknown_retry_result(step.name, attempt, v)
            _mark_done(ctx, step.name)
            ctx.steps_executed.append(step.name)
            continue

        if ctx.done(step.name):
            continue

        if step.step_type == "judgment":
            if per_repo_judgment:
                handled = per_repo_judgment(step, ctx)
                if handled is not None:
                    if not handled:
                        _mark_done(ctx, step.name)
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
                lc_result = handle_lifecycle(step, ctx)
                if lc_result and lc_result.get("ACTION") == "error":
                    return lc_result
            _mark_done(ctx, step.name)
            ctx.steps_executed.append(step.name)
            continue

    if final_gate_fn:
        gate_result = final_gate_fn(ctx)
        if gate_result is not None:
            return gate_result

    return {"ACTION": "complete", "SUMMARY": complete_summary}


def _default_execute_mechanical(step: StepDef, ctx) -> dict[str, str]:
    if not step.script_fn:
        return {}
    cmd = step.script_fn(ctx)
    if cmd is None:
        return {}
    return run_script(cmd, ctx.workspace, dry_run=ctx.dry_run, call_log=ctx.call_log)
