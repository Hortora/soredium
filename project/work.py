#!/usr/bin/env python3
"""Unified work lifecycle pipeline.

Usage:
    python3 project/work.py <command> workspace=<path> project=<path> ...

Commands: start, continue, pause, resume, next, find

Each invocation runs mechanical steps up to the next judgment point,
then prints ACTION= and exits. The LLM calls this in a loop until
ACTION=complete.
"""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

_project_dir = Path(__file__).resolve().parent
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

from orchestrator_engine import run_loop, run_script
from shared_steps import StepDef, OrchestratorContextBase
from work_progress import read_progress, update_progress, delete_progress
from conflict_resolution import make_rebase_error_handler

VALID_COMMANDS = {"start", "continue", "pause", "resume", "next", "find"}

_WORK_END_DIR = _project_dir.parent / "work-end"
_WORK_START_DIR = _project_dir.parent / "work-start"
_WORK_PAUSE_DIR = _project_dir.parent / "work-pause"
_WORK_RESUME_DIR = _project_dir.parent / "work-resume"
_PLAN_MANAGER = _project_dir.parent / "work-slot" / "plan_manager.py"
_ENRICHMENT = _project_dir.parent / "scripts" / "enrichment.py"


@dataclass
class WorkContext(OrchestratorContextBase):
    command: str = ""
    issue_n: str = ""
    issue_title: str = ""
    owner_repo: str = ""
    meta_state: str = ""
    has_handoff: bool = False
    handoff_path: Path | None = None
    has_platform_doc: bool = False
    has_protocols_dir: bool = False
    flyway_next_v: str = "none"
    design_repo_key: str = ""


def parse_args(argv: list[str]) -> dict[str, str]:
    if len(argv) < 2:
        return {"error": "missing_command"}
    command = argv[1]
    if command not in VALID_COMMANDS:
        return {"error": f"unknown_command:{command}"}
    result = {"command": command}
    for arg in argv[2:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k] = v
    return result


def build_context(args: dict[str, str]) -> WorkContext:
    ws = Path(args.get("workspace", "."))
    proj = Path(args.get("project", "."))
    progress = read_progress(ws)
    return WorkContext(
        workspace=ws,
        project=proj,
        branch=args.get("branch", ""),
        base_branch=args.get("base_branch", "main"),
        on_main=args.get("on_main", "no") == "yes",
        in_slot=args.get("in_slot", "no") == "yes",
        covers=args.get("covers", ""),
        issue_repo=args.get("issue_repo", ""),
        progress=progress,
        plan_path=Path(args["plan_path"]) if args.get("plan_path") else None,
        slot_path=Path(args["slot_path"]) if args.get("slot_path") else None,
        family_root=Path(args["family_root"]) if args.get("family_root") else None,
        command=args.get("command", ""),
        issue_n=args.get("issue_n", ""),
        issue_title=args.get("issue_title", ""),
        owner_repo=args.get("owner_repo", ""),
        meta_state=args.get("meta_state", ""),
        has_handoff=args.get("has_handoff", "no") == "yes",
        handoff_path=Path(args["handoff_path"]) if args.get("handoff_path") else None,
        has_platform_doc=args.get("has_platform_doc", "no") == "yes",
        has_protocols_dir=args.get("has_protocols_dir", "no") == "yes",
        flyway_next_v=args.get("flyway_next_v", "none"),
        design_repo_key=args.get("design_repo_key", ""),
    )


# ---------------------------------------------------------------------------
# Pause pipeline — entirely mechanical
# ---------------------------------------------------------------------------

PAUSE_STEPS: list[StepDef] = [
    StepDef("wip_commit_project", "pause", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_PAUSE_DIR / "pause_exec.py"), "commit-wip",
                str(ctx.project), f"message=WIP: pause {ctx.branch}"]),
    StepDef("wip_commit_workspace", "pause", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_PAUSE_DIR / "pause_exec.py"), "commit-wip",
                str(ctx.workspace), f"message=WIP: pause {ctx.branch}"]),
    StepDef("push_and_stack", "pause", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_PAUSE_DIR / "pause_exec.py"), "push-and-stack",
                str(ctx.workspace), str(ctx.project),
                f"branch={ctx.branch}", f"issue={ctx.issue_n}",
                f"base-branch={ctx.base_branch}"]),
]


# ---------------------------------------------------------------------------
# Resume pipeline — stack pick (judgment) + mechanical restore
# ---------------------------------------------------------------------------

def _skip_single_stack(ctx) -> bool:
    stack_depth = int(ctx.progress.get("stack_depth", "0"))
    return stack_depth <= 1


RESUME_STEPS: list[StepDef] = [
    StepDef("stack_pick", "resume", "judgment",
            skip_fn=_skip_single_stack,
            action_context_fn=lambda ctx: {"CONTEXT": "stack_pick"}),
    StepDef("pop_stack", "resume", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_project_dir / "stack.py"), "pop",
                str(ctx.workspace / ".pause-stack"),
                ctx.progress.get("selected_branch", ctx.branch)]),
    StepDef("checkout_branches", "resume", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_RESUME_DIR / "resume_exec.py"),
                "checkout-branches",
                str(ctx.project), str(ctx.workspace),
                f"branch={ctx.progress.get('selected_branch', ctx.branch)}"]),
    StepDef("rebase", "resume", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_RESUME_DIR / "resume_exec.py"), "rebase",
                str(ctx.project), str(ctx.workspace),
                f"base-branch={ctx.base_branch}"]),
    StepDef("reset_wip", "resume", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_RESUME_DIR / "resume_exec.py"), "reset-wip",
                str(ctx.project), str(ctx.workspace)]),
    StepDef("context_resume", "resume", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "load_context"}),
]


# ---------------------------------------------------------------------------
# Start pipeline — branch creation + context setup
# ---------------------------------------------------------------------------

def _skip_issue_resolved(ctx) -> bool:
    return bool(ctx.issue_n)


def _skip_no_platform_doc(ctx) -> bool:
    return not ctx.has_platform_doc


def _skip_no_protocols(ctx) -> bool:
    return not ctx.has_protocols_dir


def _skip_flyway_none(ctx) -> bool:
    return ctx.flyway_next_v == "none"


def _process_pending_archives_script(ctx):
    if not ctx.family_root:
        return None
    slot_cli = _project_dir.parent / "work-slot" / "slot_manager.py"
    return ["python3", str(slot_cli), "process-archive-requests", str(ctx.family_root)]


START_STEPS: list[StepDef] = [
    StepDef("process_archive_requests", "start", "mechanical",
            skip_fn=lambda ctx: not ctx.family_root,
            script_fn=_process_pending_archives_script),
    StepDef("sync_main", "start", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "branch_create.py"), "sync-main",
                str(ctx.project), str(ctx.workspace),
                f"base={ctx.base_branch}"]),
    StepDef("resolve_issue", "start", "judgment",
            skip_fn=_skip_issue_resolved,
            action_context_fn=lambda ctx: {
                "CONTEXT": "resolve_issue",
                "OWNER_REPO": ctx.owner_repo}),
    StepDef("stacked_pr_detect", "start", "mechanical",
            skip_fn=lambda ctx: not ctx.issue_n),
    StepDef("branch_name", "start", "judgment",
            action_context_fn=lambda ctx: {
                "CONTEXT": "branch_name",
                "ISSUE_N": ctx.issue_n,
                "ISSUE_TITLE": ctx.issue_title}),
    StepDef("flyway_scan", "start", "mechanical",
            skip_fn=_skip_flyway_none,
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "flyway_scan.py"),
                str(ctx.project), ctx.base_branch]),
    StepDef("create_branches", "start", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "branch_create.py"),
                "create-branches",
                str(ctx.project), str(ctx.workspace),
                f"branch={ctx.branch}",
                f"base={ctx.base_branch}"]),
    StepDef("design_routing", "start", "mechanical"),
    StepDef("scaffold", "start", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "scaffold.py"),
                str(ctx.workspace),
                f"branch={ctx.branch}",
                f"project-sha={ctx.progress.get('project_sha', '')}",
                f"date={ctx.progress.get('date', '')}",
                f"issue={ctx.issue_n}",
                f"issue-repo={ctx.issue_repo}",
                f"covers={ctx.covers}",
                f"flyway-next-v={ctx.flyway_next_v}",
                f"design-repo={ctx.design_repo_key}"]),
    StepDef("commit_scaffold", "start", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "branch_create.py"),
                "commit-scaffold",
                str(ctx.workspace), f"branch={ctx.branch}"]),
    StepDef("platform_coherence", "start", "judgment",
            skip_fn=_skip_no_platform_doc,
            action_context_fn=lambda ctx: {"CONTEXT": "platform_coherence"}),
    StepDef("check_protocols", "start", "judgment",
            skip_fn=_skip_no_protocols,
            action_context_fn=lambda ctx: {"CONTEXT": "check_protocols"}),
    StepDef("garden_search", "start", "mechanical"),
    StepDef("load_specs", "start", "mechanical"),
    StepDef("check_intellij", "start", "mechanical"),
    StepDef("brainstorm_offer", "start", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "brainstorm_offer"}),
]


# ---------------------------------------------------------------------------
# Continue pipeline — resume existing branch
# ---------------------------------------------------------------------------

def _skip_state_already_active(ctx) -> bool:
    return ctx.meta_state == "active"


CONTINUE_STEPS: list[StepDef] = [
    StepDef("auto_resolve_transient", "continue", "mechanical",
            skip_fn=_skip_state_already_active),
    StepDef("lifecycle_continue", "continue", "lifecycle",
            from_state="active", to_state="active", event="work_continue"),
    StepDef("health_check", "continue", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_project_dir / "work_health.py"),
                "--scope", "entry",
                "--project", str(ctx.project),
                "--workspace", str(ctx.workspace),
                "--owner-repo", ctx.owner_repo] if ctx.owner_repo else None),
    StepDef("load_specs", "continue", "mechanical"),
    StepDef("load_context", "continue", "judgment",
            action_context_fn=lambda ctx: {
                "CONTEXT": "load_context",
                "META_STATE": ctx.meta_state,
                "HAS_HANDOFF": "yes" if ctx.has_handoff else "no",
                "HANDOFF_PATH": str(ctx.handoff_path) if ctx.handoff_path else ""}),
]


# ---------------------------------------------------------------------------
# Next pipeline — advance to next issue in queue
# ---------------------------------------------------------------------------

def _skip_no_deferred(ctx) -> bool:
    return "has_deferred" not in ctx.last_output


NEXT_STEPS: list[StepDef] = [
    StepDef("lifecycle_next", "next", "lifecycle",
            from_state="active", to_state="transitioning", event="work_next"),
    StepDef("advance_issue", "next", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_PLAN_MANAGER), "advance",
                str(ctx.plan_path)] if ctx.plan_path else None),
    StepDef("tick_github", "next", "mechanical"),
    StepDef("context_refresh", "next", "mechanical"),
    StepDef("deferred_check", "next", "judgment",
            skip_fn=_skip_no_deferred,
            action_context_fn=lambda ctx: {"CONTEXT": "deferred_check"}),
]


# ---------------------------------------------------------------------------
# Find pipeline — discover and populate queue
# ---------------------------------------------------------------------------

FIND_STEPS: list[StepDef] = [
    StepDef("refresh_cache", "find", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_ENRICHMENT), "refresh",
                "--repo", ctx.owner_repo] if ctx.owner_repo else None),
    StepDef("query_recommendations", "find", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_ENRICHMENT), "what-next",
                "--repo", ctx.owner_repo, "--mode", "general",
                "--limit", "5"] if ctx.owner_repo else None),
    StepDef("present_candidates", "find", "judgment",
            action_context_fn=lambda ctx: {
                "CONTEXT": "present_candidates",
                **ctx.last_output}),
    StepDef("populate_queue", "find", "mechanical",
            script_fn=lambda ctx: [
                "python3", str(_PLAN_MANAGER), "append",
                str(ctx.plan_path),
                f"issues={ctx.progress.get('selected_issues', '')}"]
            if ctx.plan_path and ctx.progress.get("selected_issues") else None),
]


# ---------------------------------------------------------------------------
# Pipeline registry
# ---------------------------------------------------------------------------

PIPELINES: dict[str, list[StepDef]] = {
    "start": START_STEPS,
    "continue": CONTINUE_STEPS,
    "pause": PAUSE_STEPS,
    "resume": RESUME_STEPS,
    "next": NEXT_STEPS,
    "find": FIND_STEPS,
}


def _write_slot_occupant(slot_path: Path) -> None:
    """Write current PID to .occupant-pid so archive-slot can detect active sessions."""
    _slot_dir = str(slot_path.parent.parent / "work-slot")
    if _slot_dir not in sys.path:
        sys.path.insert(0, _slot_dir)
    try:
        from slot_claude import write_occupant_pid
        write_occupant_pid(slot_path)
    except ImportError:
        (slot_path / ".occupant-pid").write_text(str(os.getpid()))


def _complete_summary(command: str, ctx: WorkContext) -> str:
    parts = [f"{command} complete."]
    if ctx.issue_n:
        label = f"#{ctx.issue_n}"
        if ctx.issue_title:
            label = f"#{ctx.issue_n}: {ctx.issue_title}"
        parts.append(label)
    if ctx.branch:
        parts.append(f"branch: {ctx.branch}")
    return " ".join(parts)


def main() -> int:
    args = parse_args(sys.argv)
    if "error" in args:
        print(f"ERROR={args['error']}")
        return 1
    ctx = build_context(args)
    command = ctx.command
    if command not in PIPELINES:
        print(f"ERROR=pipeline_not_implemented:{command}")
        return 1

    if args.get("step_done"):
        from orchestrator_engine import apply_step_done
        steps = PIPELINES[command]
        mechanical = {s.name for s in steps if s.step_type == "mechanical"}
        err = apply_step_done(ctx.workspace, args["step_done"],
                              args.get("produced"),
                              mechanical_steps=mechanical)
        if err:
            for k, v in err.items():
                print(f"{k}={v}")
            return 1
        ctx.progress = read_progress(ctx.workspace)

    if args.get("skip_step"):
        from orchestrator_engine import validate_skip
        err = validate_skip(ctx.workspace, args["skip_step"])
        if err:
            for k, v in err.items():
                print(f"{k}={v}")
            return 1
        ctx.progress = read_progress(ctx.workspace)

    if ctx.in_slot and ctx.slot_path and command in ("start", "continue"):
        _write_slot_occupant(ctx.slot_path)

    steps = PIPELINES[command]
    result = run_loop(
        steps, ctx,
        on_mechanical_error=make_rebase_error_handler(),
        complete_summary=_complete_summary(command, ctx),
    )
    for k, v in result.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
