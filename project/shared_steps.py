#!/usr/bin/env python3
"""
Shared step definitions for lifecycle orchestrators.

Defines StepDef, OrchestratorContextBase, and shared judgment step
factories used by work-end, wrap, and work.py pipelines.

Moved from work-end/ to project/ for shared access (#384).
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from judgment import StepType
from progress import Progress
from repo_state import RepoDisposition, RepoType


class PipelineMode(Enum):
    BRANCH = "branch"
    SLOT = "slot"
    MAIN = "main"
    SYNC = "sync"
    CYCLE = "cycle"


ALL_MODES = frozenset(PipelineMode)
ALL_DISPOSITIONS = frozenset(RepoDisposition)
ALL_REPO_TYPES = frozenset(RepoType)


@dataclass
class StepDef:
    name: str
    phase: str
    step_type: StepType
    script_fn: Callable | None = None
    skip_fn: Callable | None = None
    action_context_fn: Callable | None = None
    verify_fn: Callable | None = None
    outcome_fn: Callable | None = None
    idempotent: bool = True
    handler: str | None = None
    response_schema: dict | None = None
    skippable: bool = True
    timeout_hint: str = "standard"
    from_state: str | None = None
    to_state: str | None = None
    event: str | None = None
    modes: frozenset[PipelineMode] = field(default_factory=lambda: ALL_MODES)
    dispositions: frozenset[RepoDisposition] = field(default_factory=lambda: ALL_DISPOSITIONS)
    disposition_repo_types: frozenset[RepoType] = field(default_factory=lambda: ALL_REPO_TYPES)
    requires: tuple[str, ...] = ()
    staleness_relevant: bool = True


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
    progress: Progress = field(default_factory=Progress)
    dry_run: bool = False
    call_log: list = field(default_factory=list)
    plan_path: Path | None = None
    slot_path: Path | None = None
    family_root: Path | None = None
    slot_num: str = ""
    last_output: dict[str, str] = field(default_factory=dict)
    steps_executed: list[str] = field(default_factory=list)
    repos: list = field(default_factory=list)

    def done(self, step: str) -> bool:
        return self.progress.is_done(step)


SWEEP_STEPS = ["forage", "protocol", "update_claude_md", "impl_doc_sync", "adr", "write_content"]

WRAP_SWEEP_STEPS = ["forage", "protocol", "update_claude_md", "write_content"]

MAX_JUDGMENT_RETRIES = 3
MAX_MECHANICAL_RETRIES = 3

JUDGMENT_STEPS_SET = {"review", "code_review",
                      "branch_audit_conformance", "branch_audit_coherence",
                      "branch_audit_structure", "branch_audit_robustness",
                      "forcing_function",
                      "sweep_config", "forage", "protocol",
                      "update_claude_md", "impl_doc_sync", "adr",
                      "write_content", "trajectory", "squash",
                      "arc42_scan", "session_rename", "garden_feedback",
                      "notes", "loose_ends", "epic_hygiene", "journal_entry",
                      "wrap_sweep_config", "handoff_write"}


def _is_sweep_deselected(step_name: str, key: str = "sweep_selected"):
    def check(ctx) -> bool:
        if key not in ctx.progress:
            return False
        raw = ctx.progress[key]
        if not raw:
            return True
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


def yield_judgment(request, workspace: Path,
                   progress) -> dict[str, str]:
    from judgment import JudgmentRequest, serialize_request
    if isinstance(request, JudgmentRequest):
        step_name = request.step
    else:
        step_name = request

    attempt = progress.get_attempt(step_name) + 1

    if attempt > MAX_JUDGMENT_RETRIES:
        return {
            "ACTION": "user_input",
            "CONTEXT": "step_failed",
            "STEP": step_name,
            "ATTEMPTS": str(MAX_JUDGMENT_RETRIES),
            "REASON": f"Validation failed after {MAX_JUDGMENT_RETRIES} attempts",
        }

    from work_progress import update_progress as update_close_progress
    update_close_progress(workspace, f"{step_name}_attempt", str(attempt))

    if isinstance(request, JudgmentRequest):
        return serialize_request(request)

    return {"ACTION": step_name}


def make_forage_step(phase: str, sweep_key: str = "sweep_selected") -> StepDef:
    return StepDef("forage", phase, StepType.JUDGMENT,
                   skip_fn=_is_sweep_deselected("forage", sweep_key))


def make_protocol_step(phase: str, sweep_key: str = "sweep_selected") -> StepDef:
    return StepDef("protocol", phase, StepType.JUDGMENT,
                   skip_fn=_is_sweep_deselected("protocol", sweep_key))


def make_update_claude_md_step(phase: str, sweep_key: str = "sweep_selected") -> StepDef:
    return StepDef("update_claude_md", phase, StepType.JUDGMENT,
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
    return StepDef("write_content", phase, StepType.JUDGMENT,
                   skip_fn=_is_sweep_deselected("write_content", sweep_key),
                   action_context_fn=_find_existing_diary)


def make_arc42_scan_step(phase: str) -> StepDef:
    return StepDef("arc42_scan", phase, StepType.JUDGMENT,
                   action_context_fn=lambda ctx: {"CONTEXT": "arc42_scan"})


def make_session_rename_step(phase: str) -> StepDef:
    return StepDef("session_rename", phase, StepType.JUDGMENT,
                   action_context_fn=lambda ctx: {"CONTEXT": "session_rename"})


def make_garden_feedback_step(phase: str) -> StepDef:
    return StepDef("garden_feedback", phase, StepType.JUDGMENT,
                   action_context_fn=lambda ctx: {"CONTEXT": "garden_feedback"})


def make_notes_step(phase: str) -> StepDef:
    return StepDef("notes", phase, StepType.JUDGMENT,
                   action_context_fn=lambda ctx: {"CONTEXT": "notes"})
