"""
Work lifecycle state detection — replaces work/work_router.py.

Single detect() function that takes a Topology and returns a WorkState.
No path resolution — all paths come from the Topology object.
"""
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_project_dir = Path(__file__).parent
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

_slot_dir = Path(__file__).parent.parent / "work-slot"
if str(_slot_dir) not in sys.path:
    sys.path.insert(0, str(_slot_dir))

from topology import Topology, find_design_file
from lifecycle import read_state as _read_state, is_transient as _is_transient


@dataclass
class WorkState:
    route: str
    on_main: bool
    in_slot: bool
    has_plan: bool
    plan_path: str
    plan_active_issue: str
    plan_position: str
    plan_batch: str
    stack_depth: int
    has_handoff: bool
    handoff_path: str
    meta_state: str
    meta_is_transient: bool
    is_epic: bool
    epic_path: str
    epic_batch: str
    epic_active_issue: str


def _run(*cmd: str, cwd: str | None = None) -> str:
    return subprocess.run(
        list(cmd), capture_output=True, text=True, cwd=cwd
    ).stdout.strip()


def detect(topo: Topology) -> WorkState:
    workspace = str(topo.workspace)
    project = str(topo.project)
    current_branch = _run("git", "-C", workspace, "branch", "--show-current")
    on_main = current_branch == "main"
    in_slot = topo.layout == "slot"

    # Pause stack
    stack_path = find_design_file(".pause-stack", topo)
    stack_depth = 0
    if stack_path and stack_path.exists():
        stack_depth = sum(
            1 for line in stack_path.read_text().splitlines()
            if line.strip().startswith("- branch:")
        )

    # Migration — convert old .meta to unified .plan if needed
    meta_file = find_design_file(".meta", topo)
    if meta_file and meta_file.exists():
        from plan_migrate import migrate_if_needed
        migrate_if_needed(meta_file.parent)

    # Plan detection via shared search
    from plan_manager import detect as _plan_detect
    has_plan = False
    plan_path = ""
    plan_active_issue = ""
    plan_position = ""
    plan_batch = ""

    plan_file = find_design_file(".plan", topo)
    if plan_file:
        detect_base = plan_file.parent.parent if plan_file.parent.name == "design" else plan_file.parent
        plan_info = _plan_detect(detect_base)
        if plan_info:
            has_plan = True
            plan_path = plan_info["plan_path"]
            plan_active_issue = str(plan_info["active_issue"] or "")
            completed = plan_info.get("completed_count", 0)
            total = plan_info.get("total_count", 0)
            plan_position = f"{completed}/{total}" if total else ""
            plan_batch = plan_info.get("current_batch") or ""

    # Epic detection via shared search
    from epic_manager import detect as _epic_detect
    is_epic = False
    epic_path = ""
    epic_batch = ""
    epic_active_issue = ""
    if not has_plan:
        epic_file = find_design_file(".epic", topo)
        if epic_file:
            detect_base = epic_file.parent.parent if epic_file.parent.name == "design" else epic_file.parent
            epic_info = _epic_detect(detect_base)
            if epic_info:
                is_epic = True
                epic_path = str(epic_info["epic_path"])
                current = epic_info.get("current_batch", 0)
                total = len(epic_info.get("batches", []))
                epic_batch = f"{current} of {total}" if total else ""
                epic_active_issue = str(epic_info.get("current_issue", ""))

    # Handoff detection — branch-scoped, working tree only
    has_handoff = False
    handoff_path = ""
    project_name = topo.project.name
    handoff_file = None
    for name in [f"HANDOFF-{project_name}.md", "HANDOFF.md"]:
        for base in [topo.workspace, topo.workspace_root]:
            candidate = base / name
            if candidate.exists():
                handoff_file = candidate
                break
        if handoff_file:
            break

    if handoff_file:
        handoff_path = str(handoff_file)
        has_handoff = True

    # Meta state
    meta_file = find_design_file(".meta", topo)
    meta_state = _read_state(meta_file) if meta_file else ""
    meta_state = meta_state or ""
    meta_is_transient = bool(meta_state and _is_transient(meta_state))

    # Routing
    project_branch = _run("git", "-C", project, "branch", "--show-current") if project != workspace else current_branch
    workspace_dirty = (
        not on_main
        and meta_file is None
        and project != workspace
        and project_branch == "main"
    )

    if on_main:
        route = "resume_stack" if stack_depth > 0 else "start"
    elif workspace_dirty:
        route = "workspace_dirty"
    else:
        route = "resume_branch"

    return WorkState(
        route=route,
        on_main=on_main,
        in_slot=in_slot,
        has_plan=has_plan,
        plan_path=plan_path,
        plan_active_issue=plan_active_issue,
        plan_position=plan_position,
        plan_batch=plan_batch,
        stack_depth=stack_depth,
        has_handoff=has_handoff,
        handoff_path=handoff_path,
        meta_state=meta_state,
        meta_is_transient=meta_is_transient,
        is_epic=is_epic,
        epic_path=epic_path,
        epic_batch=epic_batch,
        epic_active_issue=epic_active_issue,
    )
