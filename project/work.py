#!/usr/bin/env python3
"""Unified work lifecycle pipeline.

Usage:
    python3 project/work.py <command> workspace=<path> project=<path> ...

Commands: start, continue, pause, resume, next, find

Each invocation runs mechanical steps up to the next judgment point,
then prints ACTION= and exits. The LLM calls this in a loop until
ACTION=complete.
"""
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

_project_dir = Path(__file__).resolve().parent
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

from orchestrator_engine import run_loop, run_script
from shared_steps import StepDef, OrchestratorContextBase
from judgment import StepType
from work_progress import update_progress, delete_progress
from conflict_resolution import make_rebase_error_handler

VALID_COMMANDS = {"start", "continue", "pause", "resume", "next", "done", "find"}

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


# work.py argument -> the ctx.py key it is read from when the caller gives no
# workspace. One call is then enough: nothing is copied by hand between scripts.
CONTEXT_ARGS: dict[str, str] = {
    "workspace": "WORKSPACE",
    "project": "PROJECT",
    "branch": "CURRENT_BRANCH",
    "base_branch": "BASE_BRANCH",
    "on_main": "ON_MAIN",
    "in_slot": "IN_SLOT",
    "covers": "COVERS",
    "issue_repo": "ISSUE_REPO",
    "meta_state": "META_STATE",
    "owner_repo": "OWNER_REPO",
    "issue_n": "ISSUE_N",
    "has_handoff": "HAS_HANDOFF",
    "handoff_path": "HANDOFF_PATH",
    "has_platform_doc": "HAS_PLATFORM_DOC",
    "has_protocols_dir": "HAS_PROTOCOLS_DIR",
    "flyway_next_v": "FLYWAY_NEXT_V",
    "design_repo_key": "DESIGN_REPO_KEY",
    "plan_path": "PLAN_PATH",
    "slot_path": "SLOT_PATH",
    "family_root": "FAMILY_ROOT",
    "stack_depth": "STACK_DEPTH",
}


def args_from_context(context: dict[str, str]) -> dict[str, str]:
    """The work.py arguments a resolved context supplies. Empty values are left
    out so each argument keeps its own default."""
    return {arg: context[key] for arg, key in CONTEXT_ARGS.items() if context.get(key)}


def fill_from_context(args: dict[str, str], resolve=None) -> dict[str, str]:
    """Complete `args` from the resolved context when no workspace was given.

    Arguments the caller did give always win. With an explicit workspace the
    context is not resolved at all: the caller has stated where it is working.
    """
    if "error" in args or "workspace" in args:
        return args
    if resolve is None:
        import ctx as _ctx_module
        resolve = _ctx_module.resolve
    try:
        context = resolve()
    except RuntimeError as e:
        return {"error": f"context_unresolved:{e}"}
    return {**args_from_context(context), **args}


def _queue_dir(args: dict[str, str]) -> Path:
    if args.get("plan_path"):
        return Path(args["plan_path"]).parent
    return Path(args.get("workspace", "."))


# What the user can choose between when the two repos disagree and no repair
# is safe. Named so a session presents choices instead of reaching for git.
ALIGNMENT_OPTIONS: dict[str, str] = {
    "workspace_dirty": "commit_workspace_changes_then_retry,return_project_to_base_branch",
    "workspace_other": "checkout_project_branch_in_workspace,checkout_workspace_branch_in_project",
    "project_behind": "checkout_workspace_branch_in_project,return_workspace_to_base_branch",
    "queue_mismatch": "set_queue_branch_to_this_branch,checkout_queue_branch",
    "detached": "finish_or_abort_the_operation_in_progress_then_retry",
    "unreadable": "correct_the_repository_path_then_retry",
    "origin_unclear": "land_the_parent_branch_first,record_the_base_by_hand",
}


def apply_clone_guard(args: dict[str, str]) -> tuple[list[str], bool]:
    """Stop new work from starting in a canonical repo of a family that uses clones.

    In such a family the canonical repo is only the sync point (#553): work
    happens in <family>/clone/<repo>/. Work already on a branch in canonical
    is left to finish; only a start from the base branch is stopped. Inside a
    clone or a slot the parent directory holds a .slot file and this never fires.
    """
    from work_route import ROUTED
    if args.get("command", "") not in ROUTED or args.get("step_done"):
        return [], False
    if args.get("on_main") != "yes" or not args.get("project"):
        return [], False
    project = Path(args["project"]).resolve()
    family = project.parent
    if (family / ".slot").exists() or not (family / ".clone-enabled").exists():
        return [], False
    clone_dir = family / "clone" / project.name
    lines = ["ACTION=stop", "STOP_REASON=canonical_repo_of_clone_family"]
    if (clone_dir / ".slot").exists():
        workspaces = sorted(d for d in clone_dir.iterdir() if (d / ".workspace").exists())
        where = workspaces[0] if workspaces else clone_dir / project.name
        lines += [f"DETAIL=work on {project.name} happens in its clone, not in the canonical repo",
                  f"CLONE={clone_dir}",
                  f"NEXT=open the session in {where} and run work there"]
    else:
        script = Path(__file__).resolve().parent / "clone_manager.py"
        lines += [f"DETAIL={family.name} uses clones and {project.name} has none yet",
                  f"NEXT=python3 {script} create family_root={family} repo={project.name}"]
    return lines, True


def apply_alignment(args: dict[str, str]) -> tuple[dict[str, str], list[str], bool]:
    """Check that project and workspace agree before anything is routed.

    Two states are repaired without asking (see alignment_repair). Any other
    disagreement stops with ACTION=decision: nothing is switched on a guess.
    Skipped where there is nothing to compare or the caller is mid-pipeline:
    a follow-up call (`step_done=`), a named `start`, one repo serving as both,
    and slots, whose several repos this pairwise check does not model.
    """
    from work_route import ROUTED
    command = args.get("command", "")
    if command not in ROUTED or args.get("step_done"):
        return args, [], False
    if command == "start" and args.get("issue_n"):
        return args, [], False
    if args.get("in_slot") == "yes" or not args.get("project") or not args.get("workspace"):
        return args, [], False
    project, workspace = Path(args["project"]), Path(args["workspace"])
    if project.resolve() == workspace.resolve():
        return args, [], False

    from alignment import detect
    from alignment_repair import REPAIRABLE, repair
    base = args.get("base_branch", "main")
    found = detect(project, workspace, base)
    if found.state in ("on_base", "aligned"):
        return args, [], False

    def decision(reason: str, detail: str) -> tuple[dict[str, str], list[str], bool]:
        return args, [f"ALIGNMENT={found.state}", "ACTION=decision",
                      f"DECISION=alignment_{reason}", f"DETAIL={detail}",
                      f"OPTIONS={ALIGNMENT_OPTIONS.get(reason, 'resolve_then_retry')}"], True

    if found.state == "queue_mismatch":
        from queue_io import read_queue
        queue = read_queue(_queue_dir(args))
        if queue is None or queue.active_item() is None:
            return args, [], False  # a branch name left by finished work; routing decides
        return decision("queue_mismatch", found.detail)

    if found.state not in REPAIRABLE:
        return decision(found.state, found.detail)

    result = repair(found, project, workspace, base)
    if not result.ok:
        return decision(result.reason, result.detail)
    aligned = dict(args)
    aligned["branch"] = found.project_branch
    aligned["on_main"] = "no"
    lines = [f"ALIGNMENT_REPAIRED={found.state}"]
    if result.actions:
        lines.append("ALIGNMENT_ACTIONS=" + "; ".join(result.actions))
    return aligned, lines, False


def _plan_manager():
    slot_dir = str(_PLAN_MANAGER.parent)
    if slot_dir not in sys.path:
        sys.path.insert(0, slot_dir)
    import plan_manager
    return plan_manager


def _named_start(args: dict[str, str]) -> tuple[dict[str, str], list[str], bool]:
    """`start issue_n=N`: the user named the issue, so nothing is chosen here, but
    the queue must say what is being worked on before anything is branched (#561).

    The item is added when the queue lacks it, made active, and becomes what the
    work covers. Anything that would displace other work, or reopen finished
    work, stops with a decision and changes nothing.
    """
    from queue_io import read_queue
    queue_dir = _queue_dir(args)
    queue = read_queue(queue_dir)
    number = args["issue_n"].lstrip("#")
    repo = args.get("issue_repo") or (queue.state.issue_repo if queue else "") \
        or args.get("owner_repo", "")
    if queue is None or not repo or not number.isdigit():
        return args, [], False  # nothing to register against; the pipeline scaffolds it
    pm = _plan_manager()
    wanted = pm.IssueRef.parse(f"{repo}#{number}")
    same = lambda item: pm.IssueRef.parse(item.ref) == wanted  # noqa: E731
    item = next((i for i in queue.items if same(i)), None)
    active = queue.active_item()
    lines = ["ROUTE_REASON=named_start", f"ISSUE={wanted}"]

    def decision(reason: str, detail: str, options: str):
        return args, lines[1:] + ["ACTION=decision", f"DECISION={reason}",
                                  f"DETAIL={detail}", f"OPTIONS={options}"], True

    if item is not None and item.completed:
        return decision("named_issue_already_closed",
                        f"{wanted} is closed in the queue",
                        "add_it_again_as_new_work,pick_another_issue")
    if item is not None and item.done_branch:
        return decision("named_issue_done_awaiting_close",
                        f"{wanted} is finished on {item.done_branch} and waiting for work end",
                        "work_end,keep_working_on_its_branch")
    if active is not None and not same(active):
        return decision("another_item_active",
                        f"{active.ref} is active; starting {wanted} would displace it",
                        "pause_current_then_start,continue_current")

    routed = dict(args)
    if item is not None and item.active and queue.state.branch:
        routed["command"] = "continue"
        routed.pop("issue_n", None)
        return routed, ["ROUTE_REASON=named_issue_already_started", f"ISSUE={wanted}",
                        "COMMAND=continue"], False

    queue_path = queue_dir / ".queue"
    try:
        if item is None:
            # The user named the issue: no lookup, no network. An item needs a
            # title to be written and read back as itself.
            pm.append_to_queue(queue_path, [pm.QueueItem(
                ref=wanted, title=args.get("issue_title") or f"issue {number}")],
                skip_state_check=True)
            lines.append(f"QUEUED={wanted}")
        activated = pm.activate(queue_path, ref=str(wanted))
    except (pm.ActivateError, ValueError) as e:
        return args, lines + ["ACTION=error", "ERROR=named_start_failed", f"DETAIL={e}"], True
    if not activated["already"]:
        lines.append(f"ACTIVATED={wanted}")
    routed["issue_n"] = number
    routed["issue_repo"] = repo
    routed["covers"] = str(wanted)
    if activated.get("title"):
        routed.setdefault("issue_title", activated["title"])
    lines.append("COMMAND=start")
    return routed, lines, False


def apply_route(args: dict[str, str]) -> tuple[dict[str, str], list[str], bool]:
    """Turn `continue`/`next` into the pipeline the queue calls for.

    Returns (args, lines to print, stop). On a first call only: a call that
    reports a finished step (`step_done=`) is already inside a pipeline and
    names it.
    """
    from work_route import ROUTED, route
    command = args.get("command", "")
    if command not in ROUTED or args.get("step_done"):
        return args, [], False
    if command == "start" and args.get("issue_n"):
        return _named_start(args)
    from queue_io import read_queue
    queue_dir = _queue_dir(args)
    queue = read_queue(queue_dir)
    branch = args.get("branch", "")
    base = args.get("base_branch", "main")
    depth = args.get("stack_depth", "0")
    r = route(command, queue, "" if args.get("on_main") == "yes" else branch, base,
              stack_depth=int(depth) if depth.isdigit() else 0)
    if r.reason == "no_queue":
        return args, [], False

    lines = [f"ROUTE_REASON={r.reason}"]
    if r.issue:
        lines.append(f"ISSUE={r.issue}")
    if r.offer:
        lines.append("OFFER=wrap_or_continue")
        lines.append("DONE_ITEMS=" + ",".join(
            f"{i.ref}@{i.done_branch}" for i in queue.done_items()))

    if r.stop:
        if r.stop == "decision":
            options = ("checkout_active_branch,start_over_from_here"
                       if r.reason == "active_branch_not_checked_out"
                       else "switch_to_base_branch,add_item_for_this_branch")
            lines += ["ACTION=decision", f"DECISION={r.reason}", f"DETAIL={r.detail}",
                      f"OPTIONS={options}"]
        else:
            lines += ["ACTION=stop", f"DETAIL={r.detail}",
                      "NEXT=work end" if r.stop == "end"
                      else "NEXT=work find, or work start #N"]
        return args, lines, True

    if r.activate:
        _slot_dir = str(_PLAN_MANAGER.parent)
        if _slot_dir not in sys.path:
            sys.path.insert(0, _slot_dir)
        import plan_manager
        try:
            plan_manager.activate(queue_dir / ".queue", ref=r.activate)
        except (plan_manager.ActivateError, ValueError) as e:
            lines += ["ACTION=error", "ERROR=activate_failed", f"DETAIL={e}"]
            return args, lines, True
        lines.append(f"ACTIVATED={r.activate}")

    routed = dict(args)
    routed["command"] = r.run
    if r.run == "start":
        repo, _, number = r.issue.rpartition("#")
        routed.setdefault("issue_n", number)
        routed.setdefault("issue_title", r.title)
        routed.setdefault("issue_repo", repo)
    if r.activate:
        routed["covers"] = r.activate
    lines.append(f"COMMAND={r.run}")
    return routed, lines, False


def build_context(args: dict[str, str]) -> WorkContext:
    ws = Path(args.get("workspace", "."))
    proj = Path(args.get("project", "."))
    from progress import Progress
    progress = Progress.load(ws)
    from repo_state import classify_repos as _classify_repos
    repos = _classify_repos(
        project=proj,
        workspace=ws,
        branch=args.get("branch", ""),
        base_branch=args.get("base_branch", "main"),
        slot_path=Path(args["slot_path"]) if args.get("slot_path") else None,
    )
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
        repos=repos,
    )


# ---------------------------------------------------------------------------
# Pause pipeline — entirely mechanical
# ---------------------------------------------------------------------------

PAUSE_STEPS: list[StepDef] = [
    StepDef("wip_commit_project", "pause", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_PAUSE_DIR / "pause_exec.py"), "commit-wip",
                str(ctx.project), f"message=WIP: pause {ctx.branch}"]),
    StepDef("wip_commit_workspace", "pause", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_PAUSE_DIR / "pause_exec.py"), "commit-wip",
                str(ctx.workspace), f"message=WIP: pause {ctx.branch}"]),
    StepDef("push_and_stack", "pause", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_PAUSE_DIR / "pause_exec.py"), "push-and-stack",
                str(ctx.workspace), str(ctx.project),
                f"branch={ctx.branch}", f"issue={ctx.issue_n}",
                f"base-branch={ctx.base_branch}"]),
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _sync_queue_branch_script(ctx):
    if not ctx.branch:
        return None
    return ["python3", str(_PLAN_MANAGER),
            "set-state", str(ctx.plan_path) if ctx.plan_path else str(ctx.workspace / ".queue"),
            f"key=branch", f"value={ctx.branch}"]


# ---------------------------------------------------------------------------
# Resume pipeline — stack pick (judgment) + mechanical restore
# ---------------------------------------------------------------------------

def _skip_single_stack(ctx) -> bool:
    try:
        stack_depth = int(ctx.progress.get("stack_depth", "0"))
    except (ValueError, TypeError):
        stack_depth = 0
    return stack_depth <= 1


RESUME_STEPS: list[StepDef] = [
    StepDef("stack_pick", "resume", StepType.JUDGMENT,
            skip_fn=_skip_single_stack,
            action_context_fn=lambda ctx: {"CONTEXT": "stack_pick"},
            handler="handlers/stack-pick.md"),
    StepDef("pop_stack", "resume", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_project_dir / "stack.py"), "pop",
                str(ctx.workspace / ".pause-stack"),
                ctx.progress.get("selected_branch", ctx.branch)]),
    StepDef("checkout_branches", "resume", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_RESUME_DIR / "resume_exec.py"),
                "checkout-branches",
                str(ctx.project), str(ctx.workspace),
                f"branch={ctx.progress.get('selected_branch', ctx.branch)}"]),
    StepDef("rebase", "resume", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_RESUME_DIR / "resume_exec.py"), "rebase",
                str(ctx.project), str(ctx.workspace),
                f"base-branch={ctx.base_branch}"]),
    StepDef("reset_wip", "resume", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_RESUME_DIR / "resume_exec.py"), "reset-wip",
                str(ctx.project), str(ctx.workspace)]),
    StepDef("sync_queue_branch", "resume", StepType.MECHANICAL,
            script_fn=_sync_queue_branch_script),
    StepDef("context_resume", "resume", StepType.JUDGMENT,
            action_context_fn=lambda ctx: {"CONTEXT": "load_context"}),
]


# ---------------------------------------------------------------------------
# Start pipeline — branch creation + context setup
# ---------------------------------------------------------------------------

def _skip_issue_resolved(ctx) -> bool:
    return bool(ctx.issue_n)


def _skip_no_platform_doc(ctx) -> bool:
    return not ctx.has_platform_doc


def _recover_plan_context(ctx: WorkContext) -> dict[str, str]:
    marker = ctx.workspace / ".orphaned-plan"
    if not marker.exists():
        return {"CONTEXT": "recover_plan_offer"}
    try:
        data = json.loads(marker.read_text())
    except (json.JSONDecodeError, OSError):
        data = {}
    return {
        "CONTEXT": "recover_plan_offer",
        "ORPHANED_BRANCH": data.get("branch", ""),
        "ORPHANED_REMAINING": str(data.get("remaining", 0)),
        "ORPHANED_NEXT": data.get("next_title", ""),
    }


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
    StepDef("process_archive_requests", "start", StepType.MECHANICAL,
            skip_fn=lambda ctx: not ctx.family_root,
            script_fn=_process_pending_archives_script),
    StepDef("sync_main", "start", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "branch_create.py"), "sync-main",
                str(ctx.project), str(ctx.workspace),
                f"base={ctx.base_branch}"]),
    StepDef("resolve_issue", "start", StepType.JUDGMENT,
            skip_fn=_skip_issue_resolved,
            action_context_fn=lambda ctx: {
                "CONTEXT": "resolve_issue",
                "OWNER_REPO": ctx.owner_repo},
            handler="handlers/resolve-issue.md"),
    StepDef("stacked_pr_detect", "start", StepType.MECHANICAL,
            skip_fn=lambda ctx: not ctx.issue_n),
    StepDef("branch_name", "start", StepType.JUDGMENT,
            action_context_fn=lambda ctx: {
                "CONTEXT": "branch_name",
                "ISSUE_N": ctx.issue_n,
                "ISSUE_TITLE": ctx.issue_title},
            handler="handlers/branch-name.md"),
    StepDef("flyway_scan", "start", StepType.MECHANICAL,
            skip_fn=_skip_flyway_none,
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "flyway_scan.py"),
                str(ctx.project), ctx.base_branch]),
    StepDef("create_branches", "start", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "branch_create.py"),
                "create-branches",
                str(ctx.project), str(ctx.workspace),
                f"branch={ctx.branch}",
                f"base={ctx.base_branch}"]),
    StepDef("recover_plan", "start", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "recover_plan.py"),
                f"workspace={ctx.workspace}",
                f"project={ctx.project}",
                f"branch={ctx.branch}"]),
    StepDef("recover_plan_offer", "start", StepType.JUDGMENT,
            skip_fn=lambda ctx: not (ctx.workspace / ".orphaned-plan").exists(),
            action_context_fn=_recover_plan_context,
            handler="handlers/recover-plan-offer.md"),
    StepDef("design_routing", "start", StepType.MECHANICAL),
    StepDef("scaffold", "start", StepType.MECHANICAL,
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
    StepDef("commit_scaffold", "start", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_WORK_START_DIR / "branch_create.py"),
                "commit-scaffold",
                str(ctx.workspace), f"branch={ctx.branch}"]),
    StepDef("platform_coherence", "start", StepType.JUDGMENT,
            skip_fn=_skip_no_platform_doc,
            action_context_fn=lambda ctx: {"CONTEXT": "platform_coherence"},
            handler="handlers/platform-coherence.md"),
    StepDef("check_protocols", "start", StepType.JUDGMENT,
            skip_fn=_skip_no_protocols,
            action_context_fn=lambda ctx: {"CONTEXT": "check_protocols"},
            handler="handlers/check-protocols.md"),
    StepDef("garden_search", "start", StepType.MECHANICAL),
    StepDef("load_specs", "start", StepType.MECHANICAL),
    StepDef("check_intellij", "start", StepType.MECHANICAL),
    StepDef("brainstorm_offer", "start", StepType.JUDGMENT,
            action_context_fn=lambda ctx: {"CONTEXT": "brainstorm_offer"},
            handler="handlers/brainstorm-offer.md"),
]


# ---------------------------------------------------------------------------
# Continue pipeline — resume existing branch
# ---------------------------------------------------------------------------

def _skip_state_already_active(ctx) -> bool:
    return ctx.meta_state == "active"


CONTINUE_STEPS: list[StepDef] = [
    StepDef("auto_resolve_transient", "continue", StepType.MECHANICAL,
            skip_fn=_skip_state_already_active),
    StepDef("lifecycle_continue", "continue", StepType.LIFECYCLE,
            from_state="active", to_state="active", event="work_continue"),
    StepDef("sync_queue_branch", "continue", StepType.MECHANICAL,
            script_fn=_sync_queue_branch_script),
    StepDef("health_check", "continue", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_project_dir / "work_health.py"),
                "--scope", "entry",
                "--project", str(ctx.project),
                "--workspace", str(ctx.workspace),
                "--owner-repo", ctx.owner_repo] if ctx.owner_repo else None),
    StepDef("load_specs", "continue", StepType.MECHANICAL),
    StepDef("load_context", "continue", StepType.JUDGMENT,
            action_context_fn=lambda ctx: {
                "CONTEXT": "load_context",
                "META_STATE": ctx.meta_state,
                "HAS_HANDOFF": "yes" if ctx.has_handoff else "no",
                "HANDOFF_PATH": str(ctx.handoff_path) if ctx.handoff_path else ""},
            handler="handlers/load-context.md"),
]


# ---------------------------------------------------------------------------
# Next pipeline — advance to next issue in queue
# ---------------------------------------------------------------------------

def _skip_no_deferred(ctx) -> bool:
    return "has_deferred" not in ctx.last_output


def _finish_active_command(ctx) -> list[str] | None:
    """How `work next` leaves the active item.

    On a feature branch the work has not landed, so the item is marked done on
    that branch and stays open: the close ceremony lands and closes it later.
    On the base branch there is nothing left to land, so the item is closed.
    """
    if not ctx.plan_path:
        return None
    if ctx.branch and ctx.branch != ctx.base_branch:
        return ["python3", str(_PLAN_MANAGER), "mark-done", str(ctx.plan_path),
                f"branch={ctx.branch}"]
    return ["python3", str(_PLAN_MANAGER), "advance", str(ctx.plan_path)]


NEXT_STEPS: list[StepDef] = [
    StepDef("lifecycle_next", "next", StepType.LIFECYCLE,
            from_state="active", to_state="transitioning", event="work_next"),
    StepDef("advance_issue", "next", StepType.MECHANICAL,
            script_fn=_finish_active_command),
    StepDef("tick_github", "next", StepType.MECHANICAL),
    StepDef("context_refresh", "next", StepType.MECHANICAL),
    StepDef("deferred_check", "next", StepType.JUDGMENT,
            skip_fn=_skip_no_deferred,
            action_context_fn=lambda ctx: {"CONTEXT": "deferred_check"},
            handler="handlers/deferred-check.md"),
]


# ---------------------------------------------------------------------------
# Find pipeline — discover and populate queue
# ---------------------------------------------------------------------------

FIND_STEPS: list[StepDef] = [
    StepDef("refresh_cache", "find", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_ENRICHMENT), "refresh",
                "--repo", ctx.owner_repo] if ctx.owner_repo else None),
    StepDef("query_recommendations", "find", StepType.MECHANICAL,
            script_fn=lambda ctx: [
                "python3", str(_ENRICHMENT), "what-next",
                "--repo", ctx.owner_repo, "--mode", "general",
                "--limit", "5"] if ctx.owner_repo else None),
    StepDef("present_candidates", "find", StepType.JUDGMENT,
            action_context_fn=lambda ctx: {
                "CONTEXT": "present_candidates",
                **ctx.last_output},
            handler="handlers/present-candidates.md"),
    StepDef("populate_queue", "find", StepType.MECHANICAL,
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
    # `done` marks the active item finished. `next` names the same pipeline for
    # a call that reports one of its steps; a first call of `next` is routed
    # like `continue` (work_route).
    "next": NEXT_STEPS,
    "done": NEXT_STEPS,
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
    if ctx.in_slot and ctx.slot_path:
        parts.append(f"slot: {ctx.slot_path.name} at {ctx.slot_path}")
    return " ".join(parts)


def main() -> int:
    args = fill_from_context(parse_args(sys.argv))
    if "error" in args:
        print(f"ERROR={args['error']}")
        return 1
    guard_lines, stop = apply_clone_guard(args)
    for line in guard_lines:
        print(line)
    if stop:
        return 0
    args, alignment_lines, stop = apply_alignment(args)
    for line in alignment_lines:
        print(line)
    if stop:
        return 0
    args, route_lines, stop = apply_route(args)
    for line in route_lines:
        print(line)
    if stop:
        return 1 if "ACTION=error" in route_lines else 0
    ctx = build_context(args)
    command = ctx.command
    if command not in PIPELINES:
        print(f"ERROR=pipeline_not_implemented:{command}")
        return 1

    from progress import Progress

    if args.get("step_done"):
        from orchestrator_engine import apply_step_done, validate_skip
        from judgment import parse_response, validate_response, Outcome, DEFAULT_JUDGMENT_SCHEMA
        step_name = args["step_done"]
        steps = PIPELINES[command]
        mechanical = {s.name for s in steps if s.step_type == StepType.MECHANICAL}

        try:
            response = parse_response(args)
        except ValueError as e:
            print(f"ACTION=error\nERROR=invalid_outcome\nSTEP={step_name}\nDETAIL={e}")
            return 1

        step_def = next((s for s in steps if s.name == step_name), None)
        if step_def:
            schema = step_def.response_schema or DEFAULT_JUDGMENT_SCHEMA
            errors = validate_response(response, schema)
            if errors:
                print(f"ACTION=error\nERROR=schema_violation\nSTEP={step_name}\nDETAIL={'; '.join(errors)}")
                return 1

        if response.outcome == Outcome.SKIPPED:
            err = validate_skip(ctx.workspace, step_name)
            if err:
                for k, v in err.items():
                    print(f"{k}={v}")
                return 1
        elif response.outcome == Outcome.BLOCKED:
            print(f"ACTION=error\nERROR=step_blocked\nSTEP={step_name}\nREASON={response.block_reason or 'no reason'}")
            return 1
        else:
            err = apply_step_done(ctx.workspace, step_name,
                                  args.get("produced"),
                                  mechanical_steps=mechanical)
            if err:
                for k, v in err.items():
                    print(f"{k}={v}")
                return 1
        ctx.progress = Progress.load(ctx.workspace)

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
