#!/usr/bin/env python3
"""
Shared step definitions for close and wrap orchestrators.

Both work-end and wrap share judgment steps (forage, protocol,
update_claude_md, write_content, garden_feedback, notes, arc42_scan,
session_rename) and mechanical steps (loose_ends, report_init).
This module defines them once.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class StepDef:
    name: str
    phase: str
    step_type: str
    script_fn: Callable | None = None
    skip_fn: Callable | None = None
    action_context_fn: Callable | None = None
    from_state: str | None = None
    to_state: str | None = None
    event: str | None = None


@dataclass
class OrchestratorContextBase:
    workspace: Path
    project: Path
    branch: str
    base_branch: str
    on_main: bool
    in_slot: bool
    covers: str
    issue_repo: str
    progress: dict[str, str]
    dry_run: bool = False
    call_log: list = field(default_factory=list)
    plan_path: Path | None = None
    slot_path: Path | None = None
    family_root: Path | None = None
    slot_num: str = ""
    last_output: dict[str, str] = field(default_factory=dict)
    steps_executed: list[str] = field(default_factory=list)

    def done(self, step: str) -> bool:
        return self.progress.get(step) in ("done", "skipped")


SWEEP_STEPS = ["forage", "protocol", "update_claude_md", "impl_doc_sync", "adr", "write_content"]

WRAP_SWEEP_STEPS = ["forage", "protocol", "update_claude_md", "write_content"]

MAX_JUDGMENT_RETRIES = 3

JUDGMENT_STEPS_SET = {"review", "sweep_config", "forage", "protocol",
                      "update_claude_md", "impl_doc_sync", "adr",
                      "write_content", "trajectory", "squash",
                      "arc42_scan", "session_rename", "garden_feedback",
                      "notes", "loose_ends", "epic_hygiene", "journal_entry",
                      "wrap_sweep_config", "handoff_write"}


def _is_sweep_deselected(step_name: str, key: str = "sweep_selected"):
    def check(ctx) -> bool:
        raw = ctx.progress.get(key, "")
        if not raw:
            return False
        selected = {s.strip() for s in raw.split(",") if s.strip()}
        return step_name not in selected
    return check


def sweep_defaults(steps: list[str] | None = None) -> str:
    items = steps or SWEEP_STEPS
    return ",".join(f"{s}:on" for s in items)


def get_sweep_selected(progress: dict[str, str], key: str = "sweep_selected") -> set[str]:
    raw = progress.get(key, "")
    if not raw:
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}


def yield_judgment(step: str, workspace: Path,
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

    from close_progress import update_close_progress
    update_close_progress(workspace, attempt_key, str(attempt))
    result = {"ACTION": step}
    result.update(context)
    return result


def yield_user_input(step_name: str, ctx, context: dict[str, str]) -> dict[str, str]:
    attempt_key = f"{step_name}_attempt"
    attempt = int(ctx.progress.get(attempt_key, "0")) + 1
    if attempt > MAX_JUDGMENT_RETRIES:
        return {
            "ACTION": "user_input",
            "CONTEXT": "step_failed",
            "STEP": step_name,
            "ATTEMPTS": str(MAX_JUDGMENT_RETRIES),
            "REASON": f"Validation failed after {MAX_JUDGMENT_RETRIES} attempts",
        }
    from close_progress import update_close_progress
    update_close_progress(ctx.workspace, attempt_key, str(attempt))
    return {"ACTION": "user_input", **context}


def make_forage_step(phase: str, sweep_key: str = "sweep_selected") -> StepDef:
    return StepDef("forage", phase, "judgment",
                   skip_fn=_is_sweep_deselected("forage", sweep_key))


def make_protocol_step(phase: str, sweep_key: str = "sweep_selected") -> StepDef:
    return StepDef("protocol", phase, "judgment",
                   skip_fn=_is_sweep_deselected("protocol", sweep_key))


def make_update_claude_md_step(phase: str, sweep_key: str = "sweep_selected") -> StepDef:
    return StepDef("update_claude_md", phase, "judgment",
                   skip_fn=_is_sweep_deselected("update_claude_md", sweep_key))


def _find_existing_diary(ctx) -> dict[str, str]:
    """Check for an existing diary entry on this branch to revise."""
    context: dict[str, str] = {}
    blog_dir = ctx.workspace / "blog"
    if not blog_dir.is_dir():
        return context
    branch = getattr(ctx, "branch", "")
    candidates = sorted(blog_dir.glob("*.md"), reverse=True)
    for entry in candidates[:5]:
        try:
            head = entry.read_text()[:500]
            if f"series: {branch}" in head or branch in entry.name:
                context["EXISTING_DIARY"] = str(entry)
                context["DIARY_MODE"] = "revise"
                return context
        except OSError:
            continue
    context["DIARY_MODE"] = "new"
    return context


def make_write_content_step(phase: str, sweep_key: str = "sweep_selected") -> StepDef:
    return StepDef("write_content", phase, "judgment",
                   skip_fn=_is_sweep_deselected("write_content", sweep_key),
                   action_context_fn=_find_existing_diary)


def make_arc42_scan_step(phase: str) -> StepDef:
    return StepDef("arc42_scan", phase, "judgment",
                   action_context_fn=lambda ctx: {"CONTEXT": "arc42_scan"})


def make_session_rename_step(phase: str) -> StepDef:
    return StepDef("session_rename", phase, "judgment",
                   action_context_fn=lambda ctx: {"CONTEXT": "session_rename"})


def make_garden_feedback_step(phase: str) -> StepDef:
    return StepDef("garden_feedback", phase, "judgment",
                   action_context_fn=lambda ctx: {"CONTEXT": "garden_feedback"})


def make_notes_step(phase: str) -> StepDef:
    return StepDef("notes", phase, "judgment",
                   action_context_fn=lambda ctx: {"CONTEXT": "notes"})
