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
        [plan_path=<path>] [family_root=<path>] [slot_num=<N>] \
        [sweep_selected=<csv>] [skip_step=<name>] [skip_user_input_steps=yes] \
        [abort=yes] [conflict_resolved=yes] [dry_run=yes]
"""
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from close_progress import (
    read_close_progress,
    update_close_progress,
    write_close_progress,
    delete_close_progress,
    is_stale,
)
from shared_steps import StepDef, PipelineMode, ALL_MODES, ALL_DISPOSITIONS, ALL_REPO_TYPES
from repo_state import RepoDisposition, RepoType
from judgment import StepType, PRODUCED_REQUIRED_SCHEMA, FORCING_FUNCTION_SCHEMA, SQUASH_SCHEMA
from progress import Progress

CLOSE_LOG_FILE = ".close-log.jsonl"
CLOSE_FILES_TO_EXCLUDE = [".close-progress", ".close-progress.tmp", ".close-progress.done",
                          ".close-log.jsonl", ".close-report.json",
                          ".work-progress", ".work-progress.tmp"]


def _ensure_close_files_excluded(workspace: Path) -> None:
    exclude = workspace / ".git" / "info" / "exclude"
    if not exclude.exists():
        return
    content = exclude.read_text()
    added = False
    for f in CLOSE_FILES_TO_EXCLUDE:
        if f not in content:
            content += f"\n{f}"
            added = True
    if added:
        exclude.write_text(content)


def _log_call(workspace: Path, meta_state: str, result: dict[str, str],
              steps_executed: list[str], dry_run: bool = False) -> None:
    _engine_log_call(workspace, "close", result, steps_executed,
                     dry_run=dry_run,
                     extra={"meta_state": meta_state, "context": result.get("CONTEXT", "")})


SWEEP_STEPS = ["forage", "protocol", "update_claude_md", "impl_doc_sync", "doc_freshness_gate", "adr", "write_content"]

WORK_END_DIR = Path(__file__).parent

MAX_JUDGMENT_RETRIES = 3
MAX_MECHANICAL_RETRIES = 3

ABORTABLE_STATES = {"closing:review", "closing:verified"}


from orchestrator_engine import run_script as _run_script, run_loop, log_call as _engine_log_call, validate_skip, apply_step_done, validate_requires

MECHANICAL_STEPS = None  # populated after STEPS is defined

_verification_dir = str(Path(__file__).resolve().parent.parent / "verification")
if _verification_dir not in sys.path:
    sys.path.insert(0, _verification_dir)
from verification.outcomes import (
    verify_content_landed, verify_push, compose_verifications,
    verify_rebase, verify_artifacts_promoted, verify_issues_closed,
    verify_checkout_main, verify_landed_marker, verify_slot_phase_complete,
    verify_fork_next, verify_checkout_fork, verify_cleanup_scaffold,
    verify_promote_plan_next,
)

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
try:
    import worklog as _wl
except ImportError:
    _wl = None
from plan_io import copy_plan, parse_covers, remove_plan
from slot_io import parse_slot as _parse_slot


PER_REPO_SWEEP_STEPS = {"protocol", "update_claude_md", "impl_doc_sync", "doc_freshness_gate"}
PER_REPO_EXECUTE_STEPS = {"rebase", "land"}


def _resolve_repo_workspace(ctx, repo_name: str) -> Path | None:
    if not ctx.slot_path:
        return None
    candidates = [
        ctx.slot_path / f"wsp-{ctx.slot_path.parent.name}-{repo_name}",
        ctx.slot_path / f"wsp-{repo_name}",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return ctx.workspace


@dataclass
class OrchestratorContext:
    workspace: Path
    project: Path
    branch: str
    base_branch: str
    meta_state: str
    on_main: bool
    in_slot: bool
    covers: str
    issue_repo: str
    progress: Progress
    dry_run: bool = False
    call_log: list = field(default_factory=list)
    plan_path: Path | None = None
    slot_path: Path | None = None
    family_root: Path | None = None
    slot_num: str = ""
    mode: str = "end"
    pipeline_mode: PipelineMode = PipelineMode.BRANCH
    last_output: dict[str, str] = field(default_factory=dict)
    landed_shas: dict[str, str] = field(default_factory=dict)
    expected_state: str = ""
    slot_repos: list[str] = field(default_factory=list)
    steps_executed: list[str] = field(default_factory=list)
    repos: list = field(default_factory=list)
    current_repo_project: Path | None = None
    current_repo_workspace: Path | None = None
    final_progress: dict[str, str] = field(default_factory=dict)

    def done(self, step: str) -> bool:
        return self.progress.get(step) in ("done", "skipped", "skipped_error")

    def per_repo_done(self, step: str) -> bool:
        if not self.in_slot or (not self.repos and not self.slot_repos):
            return self.done(step)
        repo_names = [r.state.name for r in self.repos] if self.repos else self.slot_repos
        return all(
            self.progress.get(f"{step}:{repo}") in ("done", "skipped", "skipped_error")
            for repo in repo_names
        )

    def next_repo_for(self, step: str) -> str | None:
        if not self.in_slot or (not self.repos and not self.slot_repos):
            return None
        repo_names = [r.state.name for r in self.repos] if self.repos else self.slot_repos
        for repo in repo_names:
            if self.progress.get(f"{step}:{repo}") not in ("done", "skipped"):
                return repo
        return None


# --- Pipeline mode constants ---

M = PipelineMode
NOT_MAIN = frozenset({M.BRANCH, M.SLOT, M.SYNC, M.CYCLE})
NOT_SYNC = frozenset({M.BRANCH, M.SLOT, M.MAIN, M.CYCLE})
TERMINAL = frozenset({M.BRANCH, M.SLOT, M.MAIN})
SLOT_ONLY = frozenset({M.SLOT})
CYCLE_ONLY = frozenset({M.CYCLE})
SYNC_ONLY = frozenset({M.SYNC})
MAIN_ONLY = frozenset({M.MAIN})
BRANCH_SLOT = frozenset({M.BRANCH, M.SLOT})


# --- Pipeline mode determination ---

def _all_covers_closed(covers: str, issue_repo: str) -> bool:
    """Check if all covered issues are closed on GitHub."""
    _project_dir = str(Path(__file__).resolve().parent.parent / "project")
    if _project_dir not in sys.path:
        sys.path.insert(0, _project_dir)
    from plan_io import parse_covers
    for num in parse_covers(covers):
        try:
            result = subprocess.run(
                ["gh", "issue", "view", str(num), "--repo", issue_repo,
                 "--json", "state", "--jq", ".state"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 or result.stdout.strip() != "CLOSED":
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    return True


def _is_cycle_mode(workspace: Path, covers: str, issue_repo: str) -> bool:
    """Determine if this pipeline run is in cycle mode.

    Cycle mode: .plan has uncompleted items AND not all covered issues
    are already closed (closing all issues in cycle causes infinite loop).
    """
    _project_dir = str(Path(__file__).resolve().parent.parent / "project")
    if _project_dir not in sys.path:
        sys.path.insert(0, _project_dir)
    try:
        from plan_io import read_plan, has_uncompleted_items
        ws_plan = workspace / ".plan"
        state = read_plan(ws_plan)
        if state is None or not has_uncompleted_items(state):
            return False
        if covers and issue_repo:
            if _all_covers_closed(covers, issue_repo):
                return False
        return True
    except Exception:
        return False


def determine_pipeline_mode(
    on_main: bool,
    in_slot: bool,
    mode: str,
    workspace: Path,
    covers: str,
    issue_repo: str,
) -> PipelineMode:
    if mode == "sync":
        return PipelineMode.SYNC
    if on_main:
        return PipelineMode.MAIN
    if _is_cycle_mode(workspace, covers, issue_repo):
        return PipelineMode.CYCLE
    if in_slot:
        return PipelineMode.SLOT
    return PipelineMode.BRANCH


# --- Skip predicates (state-based only; mode predicates replaced by StepDef.modes) ---

def _skip_multi_repo_partial_close(ctx: OrchestratorContext) -> bool:
    """Skip archival when any repo in the slot has active work.

    Checks three things:
    1. Repos classified for the closing branch that haven't landed yet
    2. Any repo in the slot directory on a non-base branch (active work
       on a different branch than the one being closed)
    3. Any workspace directory with a .plan file (queued work)
    """
    if not ctx.in_slot:
        return False
    if len(ctx.repos) > 1:
        for r in ctx.repos:
            if r.state.disposition == RepoDisposition.HAS_WORK:
                if ctx.progress.get(f"land:{r.state.name}") not in ("done", "skipped", "skipped_error"):
                    return True
    if ctx.slot_path and ctx.slot_path.is_dir():
        from git_util import git
        for entry in sorted(ctx.slot_path.iterdir()):
            if not entry.is_dir() or not (entry / ".git").exists():
                continue
            if (entry / ".workspace").exists():
                if (entry / ".plan").exists() and entry.resolve() != ctx.workspace.resolve():
                    return True
                continue
            result = git(entry, "rev-parse", "--abbrev-ref", "HEAD")
            if result.returncode == 0:
                current_branch = result.stdout.strip()
                if current_branch and current_branch != ctx.base_branch:
                    return True
    return False


def _skip_no_covers(ctx: OrchestratorContext) -> bool:
    return not ctx.covers


def _skip_no_upstream(ctx: OrchestratorContext) -> bool:
    if not ctx.repos:
        return True
    return not any(r.state.has_upstream for r in ctx.repos if r.state.repo_type == RepoType.PROJECT)


def _upstream_push_script(ctx):
    return [sys.executable, str(WORK_END_DIR / "upstream_push.py"),
            f"project={ctx.project}", f"base_branch={ctx.base_branch}"]


def _is_sweep_deselected(step_name: str):
    def check(ctx: OrchestratorContext) -> bool:
        if "sweep_selected" not in ctx.progress:
            return False
        selected = _get_sweep_selected(ctx.progress)
        return step_name not in selected
    return check


# --- Script paths ---

SLOT_MANAGER = Path(__file__).parent.parent / "work-slot" / "slot_manager.py"
LIFECYCLE_SCRIPT = Path(__file__).parent.parent / "project" / "lifecycle.py"
VERIFY_SCRIPT = WORK_END_DIR / "verify_slot_close.py"
CLEANUP_SCRIPT = WORK_END_DIR / "branch_cleanup.py"
REPORT_SCRIPT = WORK_END_DIR / "close_report.py"


# --- Report helper ---

def _report_path(ctx):
    return ctx.workspace / ".close-report.json"


# --- Script builders ---

def _report_init_script(ctx):
    return [sys.executable, str(REPORT_SCRIPT), "init", str(_report_path(ctx))]


def _promote_script(ctx):
    proj = ctx.current_repo_project or ctx.project
    if ctx.in_slot and ctx.slot_path and not ctx.current_repo_workspace:
        ws = _resolve_repo_workspace(ctx, proj.name) or ctx.workspace
    else:
        ws = ctx.current_repo_workspace or ctx.workspace
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "promote", f"workspace={ws}",
            f"project={proj}", f"branch={ctx.branch}"]


def _report_promote_script(ctx):
    promoted = int(ctx.last_output.get("WORKSPACE_PROMOTED", 0)) + int(ctx.last_output.get("PROJECT_PROMOTED", 0))
    repos = f"{ctx.project.name},{ctx.workspace.name}"
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            f"step=promote", f"promoted_files={promoted}", f"target_repos={repos}"]


def _rebase_script(ctx):
    proj = ctx.current_repo_project or ctx.project
    cmd = [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
           "rebase", f"project={proj}", f"branch={ctx.branch}",
           f"base_branch={ctx.base_branch}"]
    onto_file = ctx.workspace / f".rebase-onto-{proj.name}"
    if onto_file.exists():
        cmd.append(f"rebase_onto={onto_file.read_text().strip()}")
    return cmd


def _report_rebase_script(ctx):
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            f"step=rebase", f"branch={ctx.branch}", f"base={ctx.base_branch}"]


def _report_squash_script(ctx):
    before = "?"
    after = "?"
    strategy = "unknown"
    plan_file = ctx.workspace / f".squash-plan-{ctx.project.name}.json"
    if plan_file.exists():
        try:
            data = json.loads(plan_file.read_text())
            before = str(len(data.get("commits", [])))
            after = str(len(data.get("groups", [])))
            strategy = data.get("strategy", "unknown")
        except (json.JSONDecodeError, OSError):
            pass
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            "step=squash", f"before={before}", f"after={after}", f"strategy={strategy}"]


def _write_marker_script(ctx):
    if not ctx.slot_path:
        return None
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "write-marker", f"slot_path={ctx.slot_path}", f"branch={ctx.branch}"]


def _land_script(ctx):
    if ctx.on_main:
        return None
    proj = ctx.current_repo_project or ctx.project
    ws = ctx.current_repo_workspace or ctx.workspace
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "land", f"project={proj}", f"branch={ctx.branch}",
            f"base_branch={ctx.base_branch}", f"workspace={ws}"]


def _report_land_script(ctx):
    sha = ctx.landed_shas.get(ctx.project.name, "")
    repos = ",".join(ctx.landed_shas.keys()) if ctx.landed_shas else ctx.project.name
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            f"step=land", f"landed_sha={sha}", f"pushed_repos={repos}"]


def _write_landed_script(ctx):
    if not ctx.slot_path:
        return None
    landed_path = ctx.slot_path / ".landed"
    shas = ",".join(f"{k}:{v}" for k, v in ctx.landed_shas.items() if v)
    issues = ctx.covers
    content = f"landed_shas={shas}\nissues={issues}\nbranch={ctx.branch}\n"
    if not ctx.dry_run:
        landed_path.write_text(content)
    elif ctx.call_log is not None:
        ctx.call_log.append(["(internal)", "write_landed", str(landed_path)])
    return None


def _close_issues_script(ctx):
    covers = ctx.covers
    if ctx.plan_path and ctx.plan_path.exists():
        try:
            _slot_dir = Path(__file__).parent.parent / "work-slot"
            if str(_slot_dir) not in sys.path:
                sys.path.insert(0, str(_slot_dir))
            from plan_manager import get_completed_epic_parents, parse_plan

            tree = parse_plan(ctx.plan_path)
            closable = set()
            for item in tree.queue:
                if item.ref and (item.completed or item.active):
                    closable.add(item.ref.number)

            if closable:
                all_covers = set(parse_covers(covers))
                covers = ",".join(str(n) for n in sorted(all_covers & closable))

            epic_parents = get_completed_epic_parents(ctx.plan_path)
            if epic_parents:
                existing = set(parse_covers(covers))
                for ep in epic_parents:
                    if ep.number not in existing:
                        covers = f"{covers},{ep}" if covers else str(ep)
        except Exception:
            pass
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "close-issues", f"repo={ctx.issue_repo}", f"covers={covers}"]


def _report_close_issues_script(ctx):
    closed = ctx.last_output.get("CLOSED", "0")
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            f"step=close-issues", f"closed={closed}"]


def _verify_script(ctx):
    if ctx.on_main:
        return None
    cmd = [sys.executable, str(VERIFY_SCRIPT),
           str(ctx.project), f"branch={ctx.branch}",
           f"workspace={ctx.workspace}"]
    if ctx.covers:
        cmd.append(f"covers={ctx.covers}")
    if ctx.issue_repo:
        cmd.append(f"issue_repo={ctx.issue_repo}")
    if ctx.in_slot and ctx.slot_path:
        cmd.append(f"slot_dir={ctx.slot_path}")
    return cmd


def _report_verify_script(ctx):
    verified = ctx.last_output.get("VERIFIED", "unknown")
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            f"step=verify", f"verified={verified}"]


def _archive_slot_script(ctx):
    if not ctx.slot_path or not ctx.family_root:
        return None
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "archive-slot", f"slot_path={ctx.slot_path}",
            f"family_root={ctx.family_root}", f"slot_num={ctx.slot_num}"]


def _archive_slot_context(ctx):
    return {
        "SLOT_NUM": ctx.slot_num or "",
        "SLOT_PATH": str(ctx.slot_path or ""),
        "FAMILY_ROOT": str(ctx.family_root or ""),
    }


def _report_archive_script(ctx):
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            "step=archive", f"slot={ctx.slot_num or ''}", f"dest=attic/{ctx.slot_num or ''}"]


def _elevate_plan_script(ctx):
    if not ctx.in_slot or not ctx.slot_path:
        return None
    return None


def _elevate_plan_inline(ctx: OrchestratorContext) -> dict[str, str]:
    """Elevate .plan to slot root before checkout_main switches branches.

    Must run while workspace is still on the feature branch so .plan is visible.
    Also writes the occupant PID (#366) since the session is still alive.
    """
    import shutil
    ws_plan = ctx.workspace / ".plan"
    slot_plan = ctx.slot_path / ".plan"

    if ctx.slot_path:
        _slot_dir = str(Path(__file__).resolve().parent.parent / "work-slot")
        if _slot_dir not in sys.path:
            sys.path.insert(0, _slot_dir)
        from slot_claude import write_occupant_pid
        if not ctx.dry_run:
            write_occupant_pid(ctx.slot_path)
        elif ctx.call_log is not None:
            ctx.call_log.append(["(internal)", "write_occupant_pid", str(ctx.slot_path)])

    if not ws_plan.exists():
        return {"ELEVATED": "no", "REASON": "no_plan"}

    _project_dir = str(Path(__file__).resolve().parent.parent / "project")
    if _project_dir not in sys.path:
        sys.path.insert(0, _project_dir)
    try:
        from plan_io import read_plan, has_uncompleted_items
        state = read_plan(ws_plan)
        if state is None or not has_uncompleted_items(state):
            if slot_plan.exists() and not ctx.dry_run:
                remove_plan(slot_plan)
            return {"ELEVATED": "no", "REASON": "queue_drained"}
    except Exception:
        return {"ELEVATED": "no", "REASON": "parse_error"}

    if not ctx.dry_run:
        from lifecycle import TransitionResult, commit_transition, read_state
        import shutil as _shutil
        current = read_state(ws_plan)
        if current and current.startswith("closing:"):
            result = TransitionResult(
                from_state=current, new_state="active", event="elevate",
            )
            try:
                commit_transition(ws_plan, result)
            except Exception:
                pass
        copy_plan(ws_plan, slot_plan)
    elif ctx.call_log is not None:
        ctx.call_log.append(["(internal)", "elevate_plan", str(slot_plan)])

    return {"ELEVATED": "yes", "SLOT_PLAN": str(slot_plan)}


def _promote_plan_next_inline(ctx: OrchestratorContext) -> dict[str, str]:
    """Promote .plan-next → .plan and HANDOFF-next.md → HANDOFF.md."""
    plan_next = ctx.workspace / ".plan-next"
    handoff_next = ctx.workspace / "HANDOFF-next.md"

    if not plan_next.exists() and not handoff_next.exists():
        return {"PROMOTED": "no", "REASON": "no_next_files"}

    if ctx.dry_run:
        if ctx.call_log is not None:
            if plan_next.exists():
                ctx.call_log.append(["(internal)", "promote_plan_next", str(plan_next)])
            if handoff_next.exists():
                ctx.call_log.append(["(internal)", "promote_handoff_next", str(handoff_next)])
        return {"PROMOTED": "yes", "DRY_RUN": "yes"}

    import shutil as _shutil
    promoted = []

    if plan_next.exists():
        copy_plan(plan_next, ctx.workspace / ".plan")
        remove_plan(plan_next)
        subprocess.run(
            ["git", "-C", str(ctx.workspace), "add", ".plan"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(ctx.workspace), "rm", "--ignore-unmatch", "-f", ".plan-next"],
            capture_output=True, timeout=10,
        )
        promoted.append(".plan-next")

    if handoff_next.exists():
        _shutil.copy2(handoff_next, ctx.workspace / "HANDOFF.md")
        handoff_next.unlink()
        subprocess.run(
            ["git", "-C", str(ctx.workspace), "add", "HANDOFF.md"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(ctx.workspace), "rm", "--ignore-unmatch", "-f", "HANDOFF-next.md"],
            capture_output=True, timeout=10,
        )
        promoted.append("HANDOFF-next.md")

    if promoted:
        subprocess.run(
            ["git", "-C", str(ctx.workspace), "commit", "--no-verify", "-m",
             f"chore: promote {', '.join(promoted)}"],
            capture_output=True, timeout=10,
        )

    return {"PROMOTED": "yes", "FILES": ",".join(promoted)}


def _promote_plan_next_script(ctx):
    result = _promote_plan_next_inline(ctx)
    ctx.last_output.update(result)
    return None


def _slot_repo_paths(ctx) -> list[Path]:
    if not ctx.in_slot or not ctx.slot_path or not ctx.slot_path.is_dir():
        return []
    seen = {ctx.project.resolve(), ctx.workspace.resolve()}
    extras = []
    for entry in sorted(ctx.slot_path.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        if entry.resolve() in seen:
            continue
        seen.add(entry.resolve())
        extras.append(entry)
    return extras


def _checkout_main_script(ctx):
    cmd = [sys.executable, str(CLEANUP_SCRIPT),
           "checkout-main", str(ctx.project), str(ctx.workspace)]
    if ctx.in_slot and ctx.slot_path:
        cmd.append(f"slot_path={ctx.slot_path}")
    return cmd


def _cleanup_stack_script(ctx):
    return [sys.executable, str(CLEANUP_SCRIPT),
            "cleanup-stack", str(ctx.workspace), f"branch={ctx.branch}"]


def _cleanup_scaffold_script(ctx):
    if ctx.on_main:
        return None
    cmd = [sys.executable, str(CLEANUP_SCRIPT),
           "cleanup-scaffold", str(ctx.workspace)]
    if ctx.in_slot and ctx.slot_path:
        cmd.append(f"slot_path={ctx.slot_path}")
    return cmd


def _report_scaffold_script(ctx):
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            "step=scaffold-cleanup"]


def _report_render_script(ctx):
    return [sys.executable, str(REPORT_SCRIPT), "render", str(_report_path(ctx))]


_CLOSE_ARTIFACT_NAMES = [
    ".close-progress", ".close-progress.tmp", ".close-progress.done",
    ".close-report.json", ".close-log.jsonl",
    ".work-progress", ".work-progress.tmp",
]


def _cleanup_close_artifacts(workspace: Path) -> None:
    for name in _CLOSE_ARTIFACT_NAMES:
        p = workspace / name
        if p.exists():
            p.unlink()
    plan = workspace / ".plan"
    remove_plan(plan)
    for squash_plan in workspace.glob(".squash-plan-*.json"):
        squash_plan.unlink()


# --- Main-mode special cases ---

def _push_main_mode(ctx):
    if ctx.dry_run:
        if ctx.call_log is not None:
            ctx.call_log.append(["(internal)", "push_main_mode", f"project={ctx.project}", f"workspace={ctx.workspace}"])
        sha = subprocess.run(
            ["git", "-C", str(ctx.project), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip() or "0" * 40
        return {"PUSHED": "yes", "LANDED_SHA": sha}
    for repo_path in [ctx.project, ctx.workspace]:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), "push", "origin", "main", "--no-verify"],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            return {"ERROR": f"push_failed:{repo_path.name}", "STDERR": proc.stderr[:500]}
    sha = subprocess.run(
        ["git", "-C", str(ctx.project), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    return {"PUSHED": "yes", "LANDED_SHA": sha}


def _verify_main_mode(ctx):
    if ctx.dry_run:
        if ctx.call_log is not None:
            ctx.call_log.append(["(internal)", "verify_main_mode", f"project={ctx.project}", f"workspace={ctx.workspace}"])
        return {"VERIFIED": "yes"}
    results = {}
    for repo_path in [ctx.project, ctx.workspace]:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), "log", "origin/main..main", "--oneline"],
            capture_output=True, text=True,
        )
        unpushed = proc.stdout.strip()
        if unpushed:
            results[f"{repo_path.name}_push"] = "FAIL"
        else:
            results[f"{repo_path.name}_push"] = "PASS"
    all_pass = all(v == "PASS" for v in results.values())
    results["VERIFIED"] = "yes" if all_pass else "no"
    return results


def _cleanup_main_mode(ctx):
    if ctx.dry_run:
        if ctx.call_log is not None:
            ctx.call_log.append(["(internal)", "cleanup_main_mode", f"workspace={ctx.workspace}"])
        return {"CLEANED": "yes"}
    scaffold_files = ["JOURNAL.md", ".execute-progress", ".land-ledger.jsonl", ".artifacts-promoted"]
    for f in scaffold_files:
        p = ctx.workspace / f
        if p.exists():
            subprocess.run(["git", "-C", str(ctx.workspace), "rm", "-f", str(p)],
                           capture_output=True, text=True)
    subprocess.run(["git", "-C", str(ctx.workspace), "commit", "--allow-empty",
                     "-m", "chore(work-end): cleanup branch scaffold"],
                    capture_output=True, text=True)
    subprocess.run(["git", "-C", str(ctx.workspace), "push", "--no-verify"],
                    capture_output=True, text=True)
    return {"CLEANED": "yes"}


# --- Lifecycle ---

def _build_evidence(event, ctx):
    if event == "review_pass":
        return {"review_result": "pass"}
    if event == "promote_pass":
        return {
            "promoted_files": int(ctx.last_output.get("WORKSPACE_PROMOTED", 0)) + int(ctx.last_output.get("PROJECT_PROMOTED", 0)),
            "target_repos": [ctx.project.name, ctx.workspace.name],
        }
    if event == "push_pass":
        return {
            "pushed_repos": [ctx.project.name, ctx.workspace.name],
            "pushed_shas": ctx.landed_shas,
        }
    if event == "merge_pass":
        if ctx.on_main:
            return {"landed_shas": {}, "verified_on_main": {}}
        return {
            "landed_shas": ctx.landed_shas,
            "verified_on_main": {r: True for r in ctx.landed_shas},
        }
    if event == "stamp_pass":
        if ctx.on_main:
            return {"stamp_shas": {}}
        return {"stamp_shas": ctx.landed_shas}
    if event == "sync_pass":
        return {"stamp_shas": ctx.landed_shas or {}}
    if event == "cleanup_pass":
        return {
            "repos_on_main": {ctx.project.name: True, ctx.workspace.name: True},
            "work_items_ended": True,
        }
    if event == "cleanup_main":
        return {"work_items_ended": True}
    return {}


def _fire_lifecycle(step, ctx):
    ctx.expected_state = step.to_state
    if not ctx.plan_path:
        return None
    if not ctx.plan_path.exists():
        return None

    from close_progress import _read_plan_state, LIFECYCLE_PHASE_ORDER
    actual = _read_plan_state(ctx.plan_path)
    if actual and actual in LIFECYCLE_PHASE_ORDER and step.to_state in LIFECYCLE_PHASE_ORDER:
        actual_idx = LIFECYCLE_PHASE_ORDER.index(actual)
        target_idx = LIFECYCLE_PHASE_ORDER.index(step.to_state)
        if actual_idx >= target_idx:
            return None
    if actual and actual != step.from_state:
        if actual in LIFECYCLE_PHASE_ORDER and step.from_state in LIFECYCLE_PHASE_ORDER:
            if LIFECYCLE_PHASE_ORDER.index(actual) > LIFECYCLE_PHASE_ORDER.index(step.from_state):
                return None

    evidence = _build_evidence(step.event, ctx)
    cmd = [
        sys.executable, str(LIFECYCLE_SCRIPT),
        "commit-transition", str(ctx.plan_path),
        f"from_state={step.from_state}",
        f"new_state={step.to_state}",
        f"event={step.event}",
    ]
    if evidence:
        cmd.append(f"evidence={json.dumps(evidence)}")
    result = _run_script(cmd, ctx.workspace, dry_run=ctx.dry_run, call_log=ctx.call_log)
    if result.get("ERROR"):
        err_detail = result.get("ERROR", "") + ": " + result.get("DETAIL", result.get("ERROR_DETAIL", ""))
        if "CONCURRENT_MODIFICATION" in err_detail:
            refreshed = _read_plan_state(ctx.plan_path)
            if refreshed in LIFECYCLE_PHASE_ORDER and step.to_state in LIFECYCLE_PHASE_ORDER:
                if LIFECYCLE_PHASE_ORDER.index(refreshed) >= LIFECYCLE_PHASE_ORDER.index(step.to_state):
                    return None
        return {
            "ACTION": "error",
            "ERROR": f"LIFECYCLE_TRANSITION_FAILED",
            "STEP": step.name,
            "FROM_STATE": step.from_state,
            "TO_STATE": step.to_state,
            "EVENT": step.event,
            "DETAIL": err_detail,
        }
    return None


# --- Reconciliation ---

def _check_rebase(ws, proj):
    proc = subprocess.run(
        ["git", "-C", str(proj), "merge-base", "--is-ancestor", "main", "HEAD"],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def _check_checkout_main(ws, proj):
    for repo in [proj, ws]:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        )
        if proc.stdout.strip() != "main":
            return False
    return True


def _check_cleanup_stack(ws, proj):
    for stack_file in [ws / ".pause-stack", ws / "design" / ".pause-stack"]:
        if stack_file.exists():
            content = stack_file.read_text()
            branch = subprocess.run(
                ["git", "-C", str(proj), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True,
            ).stdout.strip()
            if branch and f"branch: {branch}" in content:
                return False
    return True


EVIDENCE_CHECKS: dict[str, Callable] = {
    "land": lambda ws, proj: (ws / ".execute-progress").exists(),
    "rebase": _check_rebase,
    "close_issues": lambda ws, proj: True,
    "verify": lambda ws, proj: True,
    "cleanup": lambda ws, proj: not (ws / "JOURNAL.md").exists(),
    "checkout_main": _check_checkout_main,
    "cleanup_stack": _check_cleanup_stack,
    "promote": lambda ws, proj: True,
}
JUDGMENT_STEPS_SET = {"code_review", "branch_audit_conformance",
                      "branch_audit_coherence", "branch_audit_structure",
                      "branch_audit_robustness", "loose_ends", "forcing_function",
                      "sweep_config", "forage", "protocol",
                      "update_claude_md", "impl_doc_sync", "doc_freshness_gate", "adr",
                      "write_content", "queue_decision", "trajectory", "squash",
                      "upstream_push", "archive_slot",
                      "arc42_scan", "session_rename", "garden_feedback", "notes"}


_ALL_PER_REPO_STEPS = PER_REPO_EXECUTE_STEPS | PER_REPO_SWEEP_STEPS


def _phase_skip(progress: dict[str, str], meta_state: str,
                workspace: Path,
                slot_repos: list[str] | None = None) -> dict[str, str]:
    """Auto-complete steps whose phase is behind meta_state.

    When meta_state=closing:stamped but close-progress has no review
    entries, the loop would re-run review steps. This function fills
    in the gaps so the loop skips past completed phases.

    In slot mode (slot_repos non-empty), per-repo steps get composite
    keys (promote:engine=done) instead of a single key (promote=done).
    A single key would make ctx.done() bypass the per-repo fan-out.
    """
    from close_progress import STEP_TO_PHASE, LIFECYCLE_PHASE_ORDER
    if meta_state not in LIFECYCLE_PHASE_ORDER:
        return progress
    meta_idx = LIFECYCLE_PHASE_ORDER.index(meta_state)
    if meta_idx == 0:
        return progress
    _NEVER_PHASE_SKIP = {"checkout_main", "cleanup", "cleanup_stack"}
    filled = False
    for step_def in STEPS:
        if step_def.name in _NEVER_PHASE_SKIP:
            continue
        step_phase = STEP_TO_PHASE.get(step_def.name)
        if not step_phase or step_phase not in LIFECYCLE_PHASE_ORDER:
            continue
        phase_idx = LIFECYCLE_PHASE_ORDER.index(step_phase)
        if phase_idx >= meta_idx:
            continue
        if slot_repos and step_def.name in _ALL_PER_REPO_STEPS:
            for repo in slot_repos:
                composite = f"{step_def.name}:{repo}"
                if composite not in progress:
                    progress[composite] = "done"
                    filled = True
        else:
            if step_def.name not in progress:
                progress[step_def.name] = "done"
                filled = True
    if filled:
        write_close_progress(workspace, progress)
    return progress


def _reconcile(workspace: Path, project: Path,
               progress: dict[str, str],
               meta_state: str) -> tuple[dict[str, str], list[str]]:
    from close_progress import STEP_TO_PHASE, LIFECYCLE_PHASE_ORDER
    meta_idx = LIFECYCLE_PHASE_ORDER.index(meta_state) if meta_state in LIFECYCLE_PHASE_ORDER else 0
    corrections = []
    corrected = dict(progress)
    for step, status in list(progress.items()):
        if status != "done":
            continue
        if step.startswith("report_") or step.startswith("fallback_") or step.startswith("_"):
            continue
        if "_attempt" in step or step in ("sweep_selected", "last_yielded"):
            continue
        if step in JUDGMENT_STEPS_SET:
            continue
        base_step = step.split(":")[0] if ":" in step else step
        step_phase = STEP_TO_PHASE.get(base_step, "closing:review")
        step_idx = LIFECYCLE_PHASE_ORDER.index(step_phase) if step_phase in LIFECYCLE_PHASE_ORDER else 0
        if step_idx >= meta_idx:
            continue
        check = EVIDENCE_CHECKS.get(step)
        if check and not check(workspace, project):
            del corrected[step]
            corrections.append(step)
    return corrected, corrections


# --- Step sequence ---

REVIEW_SUB_STEPS = [
    "code_review", "branch_audit_conformance", "branch_audit_coherence",
    "branch_audit_structure", "branch_audit_robustness",
    "loose_ends", "forcing_function",
]


def _diff_range_context(ctx):
    return {"DIFF_RANGE": f"{ctx.base_branch}..{ctx.branch}"}


def _dimension_context(dimension: str):
    def context(ctx):
        return {"DIFF_RANGE": f"{ctx.base_branch}..{ctx.branch}", "DIMENSION": dimension}
    return context


def _loose_ends_context(ctx):
    return {
        "WORKSPACE": str(ctx.workspace),
        "PROJECT": str(ctx.project),
        "BRANCH": ctx.branch,
        "COVERS": ctx.covers or "",
        "BASE_BRANCH": ctx.base_branch,
    }


def _skip_no_queue_remaining(ctx) -> bool:
    """Skip queue_decision when .plan has no remaining items after the active one."""
    ws_plan = ctx.workspace / ".plan"
    if not ws_plan.exists():
        return True
    _proj_dir = str(Path(__file__).resolve().parent.parent / "project")
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)
    try:
        from plan_io import read_plan
        state = read_plan(ws_plan)
        if state is None:
            return True
        remaining = [it for it in state.queue_items if not it.completed and not it.active]
        return len(remaining) == 0
    except Exception:
        return True


def _queue_decision_context(ctx):
    ws_plan = ctx.workspace / ".plan"
    remaining = 0
    next_title = ""
    _proj_dir = str(Path(__file__).resolve().parent.parent / "project")
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)
    try:
        from plan_io import read_plan
        state = read_plan(ws_plan)
        if state:
            future = [it for it in state.queue_items if not it.completed and not it.active]
            remaining = len(future)
            if future:
                next_title = future[0].title
    except Exception:
        pass
    return {
        "CONTEXT": "queue_decision",
        "REMAINING": str(remaining),
        "NEXT_TITLE": next_title,
    }


def _has_remaining_queue_items(ctx) -> bool:
    """Check if the .plan has uncompleted queue items beyond the active one."""
    ws_plan = ctx.workspace / ".plan"
    if not ws_plan.exists():
        return False
    _proj_dir = str(Path(__file__).resolve().parent.parent / "project")
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)
    try:
        from plan_io import read_plan
        state = read_plan(ws_plan)
        if state is None:
            return False
        return any(not it.completed and not it.active for it in state.queue_items)
    except Exception:
        return False


def _skip_cleanup_pass_when_remaining(ctx) -> bool:
    """Skip cleanup_pass (→ idle) when plan has remaining items."""
    return _has_remaining_queue_items(ctx)


def _skip_cleanup_cycle_when_empty(ctx) -> bool:
    """Skip cleanup_cycle (→ active) when plan has NO remaining items."""
    return not _has_remaining_queue_items(ctx)


def _advance_queue_script(ctx):
    """Advance .plan queue to next item when remaining items exist."""
    ws_plan = ctx.workspace / ".plan"
    if not ws_plan.exists():
        return None
    plan_mgr = Path(__file__).resolve().parent.parent / "work-slot" / "plan_manager.py"
    return [sys.executable, str(plan_mgr), "advance", str(ws_plan)]


def _skip_fork_next(ctx) -> bool:
    """Skip fork_next_branch unless the user chose fork_next in queue_decision."""
    return ctx.progress.get("queue_decision_produced") != "fork_next"


def _fork_next_script(ctx):
    fork_script = Path(__file__).parent / "fork_next_branch.py"
    if not fork_script.exists():
        return None
    return [
        sys.executable, str(fork_script),
        f"workspace={ctx.workspace}",
        f"project={ctx.project}",
        f"branch={ctx.branch}",
        f"base_branch={ctx.base_branch}",
    ]


def _skip_checkout_fork(ctx) -> bool:
    """Skip checkout_fork unless fork_next was chosen and a fork branch was created."""
    return not ctx.progress.get("fork_next_branch")


def _checkout_fork_script(ctx):
    fork_branch = ctx.progress.get("fork_next_branch", "")
    if not fork_branch:
        return None
    return [
        sys.executable, "-c",
        f"import subprocess; "
        f"subprocess.run(['git', '-C', '{ctx.workspace}', 'checkout', '{fork_branch}'], capture_output=True); "
        f"subprocess.run(['git', '-C', '{ctx.project}', 'checkout', '{fork_branch}'], capture_output=True); "
        f"print('CHECKED_OUT={fork_branch}')"
    ]


def _forcing_function_context(ctx):
    findings_path = ctx.workspace / ".audit" / "findings.jsonl"
    branch = ctx.branch
    count = 0
    other_count = 0
    if findings_path.exists():
        for line in findings_path.read_text().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("status", "open") == "open":
                    if entry.get("branch") == branch:
                        count += 1
                    else:
                        other_count += 1
            except (json.JSONDecodeError, ValueError):
                pass
    result = {"CONTEXT": "forcing_function", "OPEN_FINDINGS": str(count),
              "BRANCH": branch}
    if other_count:
        result["OTHER_BRANCH_FINDINGS"] = str(other_count)
    return result


# --- Verify functions (postcondition checks) ---

def _verify_produced_required(workspace: Path, produced: str | None, **_kw) -> str | None:
    if produced is None:
        return "produced count required — retry with: step_done=<STEP> produced=N (use 0 if no findings)"
    return None


def _verify_squash(workspace: Path, produced: str | None, **_kw) -> str | None:
    for plan_file in workspace.glob(".squash-plan-*.json"):
        try:
            data = json.loads(plan_file.read_text())
            if not data.get("verified"):
                repo = plan_file.name.replace(".squash-plan-", "").replace(".json", "")
                return (f"Squash plan for {repo} not verified — "
                        "run 'git diff backup..HEAD' to confirm diff=0, "
                        "then set verified:true in the plan file")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _verify_forcing_function(workspace: Path, produced: str | None, branch: str = "") -> str | None:
    findings_path = workspace / ".audit" / "findings.jsonl"
    if not findings_path.exists():
        return None
    _project = Path(__file__).resolve().parent.parent / "project"
    sys.path.insert(0, str(_project))
    try:
        from findings import read_findings
        findings = read_findings(findings_path)
        open_findings = [f for f in findings if f.get("status", "open") == "open" and f.get("branch") == branch]
        if open_findings:
            details = "; ".join(f.get("detail", "?")[:40] for f in open_findings[:3])
            return f"{len(open_findings)} open finding(s): {details}"
    except ImportError:
        pass
    return None


STEPS: list[StepDef] = [
    # --- closing:review (sub-steps) ---
    StepDef("report_init", "closing:review", StepType.MECHANICAL,
            script_fn=_report_init_script),
    StepDef("code_review", "closing:review", StepType.JUDGMENT,
            dispositions=frozenset({RepoDisposition.HAS_WORK}),
            disposition_repo_types=frozenset({RepoType.PROJECT}),
            action_context_fn=_diff_range_context,
            verify_fn=_verify_produced_required,
            handler="handlers/review.md",
            response_schema=PRODUCED_REQUIRED_SCHEMA,
            timeout_hint="extended"),
    StepDef("branch_audit_conformance", "closing:review", StepType.JUDGMENT,
            dispositions=frozenset({RepoDisposition.HAS_WORK}),
            disposition_repo_types=frozenset({RepoType.PROJECT}),
            action_context_fn=_dimension_context("conformance"),
            verify_fn=_verify_produced_required,
            handler="handlers/review.md",
            response_schema=PRODUCED_REQUIRED_SCHEMA,
            timeout_hint="extended"),
    StepDef("branch_audit_coherence", "closing:review", StepType.JUDGMENT,
            dispositions=frozenset({RepoDisposition.HAS_WORK}),
            disposition_repo_types=frozenset({RepoType.PROJECT}),
            action_context_fn=_dimension_context("coherence"),
            verify_fn=_verify_produced_required,
            handler="handlers/review.md",
            response_schema=PRODUCED_REQUIRED_SCHEMA,
            timeout_hint="extended"),
    StepDef("branch_audit_structure", "closing:review", StepType.JUDGMENT,
            dispositions=frozenset({RepoDisposition.HAS_WORK}),
            disposition_repo_types=frozenset({RepoType.PROJECT}),
            action_context_fn=_dimension_context("structure"),
            verify_fn=_verify_produced_required,
            handler="handlers/review.md",
            response_schema=PRODUCED_REQUIRED_SCHEMA,
            timeout_hint="extended"),
    StepDef("branch_audit_robustness", "closing:review", StepType.JUDGMENT,
            dispositions=frozenset({RepoDisposition.HAS_WORK}),
            disposition_repo_types=frozenset({RepoType.PROJECT}),
            action_context_fn=_dimension_context("robustness"),
            verify_fn=_verify_produced_required,
            handler="handlers/review.md",
            response_schema=PRODUCED_REQUIRED_SCHEMA,
            timeout_hint="extended"),
    StepDef("loose_ends", "closing:review", StepType.JUDGMENT,
            dispositions=frozenset({RepoDisposition.HAS_WORK}),
            disposition_repo_types=frozenset({RepoType.PROJECT}),
            action_context_fn=_loose_ends_context,
            verify_fn=_verify_produced_required,
            handler="handlers/review.md",
            response_schema=PRODUCED_REQUIRED_SCHEMA),
    StepDef("forcing_function", "closing:review", StepType.JUDGMENT,
            dispositions=frozenset({RepoDisposition.HAS_WORK}),
            disposition_repo_types=frozenset({RepoType.PROJECT}),
            action_context_fn=_forcing_function_context,
            verify_fn=_verify_forcing_function,
            handler="handlers/review.md",
            response_schema=FORCING_FUNCTION_SCHEMA),
    StepDef("sweep_config", "closing:review", StepType.JUDGMENT,
            action_context_fn=lambda ctx: {"ITEMS": _sweep_defaults(),
                                           "COMPLETE_WITH": "sweep_selected=<comma-separated-list>"},
            handler="handlers/sweep_config.md",
            timeout_hint="quick"),
    StepDef("forage", "closing:review", StepType.JUDGMENT,
            skip_fn=_is_sweep_deselected("forage")),
    StepDef("protocol", "closing:review", StepType.JUDGMENT,
            skip_fn=_is_sweep_deselected("protocol")),
    StepDef("update_claude_md", "closing:review", StepType.JUDGMENT,
            skip_fn=_is_sweep_deselected("update_claude_md")),
    StepDef("impl_doc_sync", "closing:review", StepType.JUDGMENT,
            skip_fn=_is_sweep_deselected("impl_doc_sync")),
    StepDef("doc_freshness_gate", "closing:review", StepType.JUDGMENT,
            skip_fn=_is_sweep_deselected("doc_freshness_gate")),
    StepDef("adr", "closing:review", StepType.JUDGMENT,
            skip_fn=_is_sweep_deselected("adr")),
    StepDef("write_content", "closing:review", StepType.JUDGMENT,
            skip_fn=_is_sweep_deselected("write_content")),

    # --- queue continuation decision ---
    StepDef("queue_decision", "closing:review", StepType.JUDGMENT,
            modes=NOT_SYNC,
            skip_fn=_skip_no_queue_remaining,
            action_context_fn=_queue_decision_context,
            handler="handlers/queue-decision.md"),
    StepDef("fork_next_branch", "closing:review", StepType.MECHANICAL,
            requires=("queue_decision",),
            skip_fn=_skip_fork_next,
            script_fn=_fork_next_script,
            outcome_fn=lambda ctx: verify_fork_next(ctx.workspace, ctx.progress)),

    # --- lifecycle: review -> verified ---
    StepDef("review_pass", "closing:review", StepType.LIFECYCLE,
            from_state="closing:review", to_state="closing:verified", event="review_pass"),

    # --- closing:verified ---
    StepDef("promote", "closing:verified", StepType.MECHANICAL,
            script_fn=_promote_script,
            outcome_fn=lambda ctx: verify_artifacts_promoted(
                getattr(ctx, "current_repo_workspace", None) or ctx.workspace,
                getattr(ctx, "current_repo_project", None) or ctx.project,
                ctx.branch, ctx.base_branch)),
    StepDef("report_promote", "closing:verified", StepType.MECHANICAL,
            requires=("promote",),
            script_fn=_report_promote_script),
    StepDef("promote_pass", "closing:verified", StepType.LIFECYCLE,
            from_state="closing:verified", to_state="closing:promoted", event="promote_pass"),

    # --- closing:promoted ---
    StepDef("trajectory", "closing:promoted", StepType.JUDGMENT,
            action_context_fn=lambda ctx: {"COVERS": ctx.covers, "OWNER_REPO": ctx.issue_repo}),
    StepDef("rebase", "closing:promoted", StepType.MECHANICAL,
            modes=NOT_MAIN,
            script_fn=_rebase_script,
            outcome_fn=lambda ctx: verify_rebase(
                getattr(ctx, "current_repo_project", None) or ctx.project,
                ctx.branch, ctx.base_branch)),
    StepDef("report_rebase", "closing:promoted", StepType.MECHANICAL,
            modes=NOT_MAIN,
            requires=("rebase",),
            script_fn=_report_rebase_script),
    StepDef("squash", "closing:promoted", StepType.JUDGMENT,
            modes=NOT_MAIN,
            requires=("rebase",),
            dispositions=frozenset({RepoDisposition.HAS_WORK}),
            disposition_repo_types=frozenset({RepoType.PROJECT}),
            action_context_fn=lambda ctx: {"REPOS": ctx.project.name},
            verify_fn=_verify_squash,
            response_schema=SQUASH_SCHEMA),
    StepDef("report_squash", "closing:promoted", StepType.MECHANICAL,
            modes=NOT_MAIN,
            requires=("squash",),
            script_fn=_report_squash_script),
    StepDef("write_marker", "closing:promoted", StepType.MECHANICAL,
            modes=SLOT_ONLY,
            requires=("squash",),
            script_fn=_write_marker_script,
            outcome_fn=lambda ctx: verify_slot_phase_complete(ctx.slot_path, ".phase-a-complete")),
    StepDef("land", "closing:promoted", StepType.MECHANICAL,
            requires=("squash",),
            script_fn=_land_script,
            outcome_fn=lambda ctx: compose_verifications("land",
                verify_push(
                    getattr(ctx, "current_repo_project", None) or ctx.project,
                    ctx.base_branch),
                verify_content_landed(
                    getattr(ctx, "current_repo_project", None) or ctx.project,
                    ctx.landed_shas.get(
                        (getattr(ctx, "current_repo_project", None) or ctx.project).name, ""),
                    ctx.base_branch)),
            idempotent=False),
    StepDef("report_land", "closing:promoted", StepType.MECHANICAL,
            requires=("land",),
            script_fn=_report_land_script),
    StepDef("push_pass", "closing:promoted", StepType.LIFECYCLE,
            requires=("land",),
            from_state="closing:promoted", to_state="closing:pushed", event="push_pass"),
    StepDef("merge_pass", "closing:pushed", StepType.LIFECYCLE,
            from_state="closing:pushed", to_state="closing:merged", event="merge_pass"),
    StepDef("cycle_pass", "closing:merged", StepType.LIFECYCLE,
            modes=CYCLE_ONLY,
            from_state="closing:merged", to_state="active",
            event="issue_cycle"),
    StepDef("stamp_pass", "closing:merged", StepType.LIFECYCLE,
            modes=TERMINAL,
            from_state="closing:merged", to_state="closing:stamped", event="stamp_pass"),

    # --- closing:stamped ---
    StepDef("write_landed", "closing:stamped", StepType.MECHANICAL,
            modes=SLOT_ONLY,
            script_fn=_write_landed_script,
            outcome_fn=lambda ctx: verify_landed_marker(ctx.slot_path)),
    StepDef("verify", "closing:stamped", StepType.MECHANICAL,
            modes=NOT_SYNC,
            script_fn=_verify_script),
    StepDef("report_verify", "closing:stamped", StepType.MECHANICAL,
            modes=NOT_SYNC,
            requires=("verify",),
            script_fn=_report_verify_script),
    StepDef("close_issues", "closing:stamped", StepType.MECHANICAL,
            modes=NOT_SYNC,
            requires=("verify",),
            skip_fn=_skip_no_covers,
            script_fn=_close_issues_script,
            outcome_fn=lambda ctx: verify_issues_closed(ctx.issue_repo, ctx.covers, ctx.plan_path)),
    StepDef("report_close_issues", "closing:stamped", StepType.MECHANICAL,
            modes=NOT_SYNC,
            requires=("close_issues",),
            skip_fn=_skip_no_covers,
            script_fn=_report_close_issues_script),
    StepDef("upstream_push", "closing:stamped", StepType.MECHANICAL,
            skip_fn=_skip_no_upstream,
            script_fn=_upstream_push_script,
            outcome_fn=lambda ctx: verify_push(
                getattr(ctx, "current_repo_project", None) or ctx.project,
                ctx.base_branch)),
    StepDef("archive_slot", "closing:stamped", StepType.JUDGMENT,
            modes=SLOT_ONLY,
            skip_fn=_skip_multi_repo_partial_close,
            action_context_fn=_archive_slot_context,
            handler="handlers/archive_slot.md"),
    StepDef("report_archive", "closing:stamped", StepType.MECHANICAL,
            modes=SLOT_ONLY,
            requires=("archive_slot",),
            skip_fn=_skip_multi_repo_partial_close,
            script_fn=_report_archive_script),
    StepDef("elevate_plan", "closing:stamped", StepType.MECHANICAL,
            modes=SLOT_ONLY,
            script_fn=_elevate_plan_script),
    StepDef("checkout_main", "closing:stamped", StepType.MECHANICAL,
            modes=BRANCH_SLOT,
            script_fn=_checkout_main_script,
            outcome_fn=lambda ctx: verify_checkout_main(ctx.project, ctx.workspace,
                                                        _slot_repo_paths(ctx))),
    StepDef("cleanup_stack", "closing:stamped", StepType.MECHANICAL,
            modes=BRANCH_SLOT,
            script_fn=_cleanup_stack_script),
    StepDef("cleanup", "closing:stamped", StepType.MECHANICAL,
            modes=TERMINAL,
            script_fn=_cleanup_scaffold_script,
            outcome_fn=lambda ctx: verify_cleanup_scaffold(ctx.workspace)),
    StepDef("report_scaffold", "closing:stamped", StepType.MECHANICAL,
            modes=TERMINAL,
            requires=("cleanup",),
            script_fn=_report_scaffold_script),
    StepDef("checkout_fork", "closing:stamped", StepType.MECHANICAL,
            requires=("checkout_main",),
            skip_fn=_skip_checkout_fork,
            script_fn=_checkout_fork_script,
            outcome_fn=lambda ctx: verify_checkout_fork(ctx.workspace, ctx.progress)),
    StepDef("arc42_scan", "closing:stamped", StepType.JUDGMENT,
            modes=TERMINAL,
            action_context_fn=lambda ctx: {"CONTEXT": "arc42_scan"},
            handler="handlers/user_input.md",
            timeout_hint="quick"),
    StepDef("session_rename", "closing:stamped", StepType.JUDGMENT,
            modes=TERMINAL,
            action_context_fn=lambda ctx: {"CONTEXT": "session_rename"},
            handler="handlers/user_input.md",
            timeout_hint="quick"),
    StepDef("garden_feedback", "closing:stamped", StepType.JUDGMENT,
            modes=TERMINAL,
            action_context_fn=lambda ctx: {"CONTEXT": "garden_feedback"},
            handler="handlers/user_input.md",
            timeout_hint="quick"),
    StepDef("notes", "closing:stamped", StepType.JUDGMENT,
            modes=TERMINAL,
            action_context_fn=lambda ctx: {"CONTEXT": "notes"},
            handler="handlers/user_input.md",
            timeout_hint="quick"),

    # --- lifecycle: stamped -> idle/drained/active(sync) ---
    StepDef("sync_pass", "closing:stamped", StepType.LIFECYCLE,
            modes=SYNC_ONLY,
            from_state="closing:stamped", to_state="active", event="sync_pass"),

    # --- continuation promotion (runs in all modes) ---
    StepDef("promote_plan_next", "closing:stamped", StepType.MECHANICAL,
            script_fn=_promote_plan_next_script,
            outcome_fn=lambda ctx: verify_promote_plan_next(ctx.workspace)),

    StepDef("advance_queue", "closing:stamped", StepType.MECHANICAL,
            modes=BRANCH_SLOT,
            skip_fn=_skip_cleanup_cycle_when_empty,
            script_fn=_advance_queue_script),
    StepDef("cleanup_cycle", "closing:stamped", StepType.LIFECYCLE,
            modes=BRANCH_SLOT,
            skip_fn=_skip_cleanup_cycle_when_empty,
            from_state="closing:stamped", to_state="active", event="issue_cycle"),
    StepDef("cleanup_pass", "closing:stamped", StepType.LIFECYCLE,
            modes=BRANCH_SLOT,
            skip_fn=_skip_cleanup_pass_when_remaining,
            from_state="closing:stamped", to_state="idle", event="cleanup_pass"),
    StepDef("cleanup_main", "closing:stamped", StepType.LIFECYCLE,
            modes=MAIN_ONLY,
            from_state="closing:stamped", to_state="drained", event="cleanup_main"),

    # --- post-close ---
    StepDef("delete_progress", "idle", StepType.MECHANICAL),
    StepDef("report_render", "idle", StepType.MECHANICAL,
            script_fn=_report_render_script),
]

MECHANICAL_STEPS = {s.name for s in STEPS if s.step_type == StepType.MECHANICAL}
validate_requires(STEPS)


def _record(event_type, branch, project, issue_repo, dry_run, **kwargs):
    if not _wl or dry_run:
        return
    try:
        conn = _wl.connect()
        _wl.record_close_event(
            conn, event_type, "close", branch,
            repo_path=str(project), issue_repo=issue_repo,
            **kwargs,
        )
        conn.close()
    except Exception:
        pass


def parse_args(argv: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for arg in argv:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k] = v
    return result


def run_orchestrator(args: dict[str, str]) -> dict[str, str]:
    workspace = Path(args["workspace"])
    _ensure_close_files_excluded(workspace)
    project = Path(args.get("project", ""))
    branch = args.get("branch", "")
    base_branch = args.get("base_branch", "main")
    meta_state = args.get("meta_state", "closing:review")
    on_main = args.get("on_main", "no") == "yes"
    in_slot = args.get("in_slot", "no") == "yes"
    covers = args.get("covers", "")
    issue_repo = args.get("issue_repo", "")
    dry_run = args.get("dry_run", "no") == "yes"
    plan_path = Path(args["plan_path"]) if args.get("plan_path") else None
    slot_path = Path(args["slot_path"]) if args.get("slot_path") else None
    family_root = Path(args["family_root"]) if args.get("family_root") else None
    slot_num = args.get("slot_num", "")
    mode = args.get("mode", "end")

    if args.get("abort") == "yes":
        return _handle_abort(workspace, meta_state)

    if meta_state in ("scaffolded", "transitioning") and plan_path and plan_path.exists():
        try:
            _run_script(
                [sys.executable, str(LIFECYCLE_SCRIPT),
                 "commit-transition", str(plan_path),
                 f"from_state={meta_state}", "new_state=active",
                 "event=auto_setup"],
                workspace, dry_run=dry_run,
            )
            meta_state = "active"
        except Exception:
            pass

    if meta_state == "active" and plan_path and plan_path.exists():
        try:
            _run_script(
                [sys.executable, str(LIFECYCLE_SCRIPT),
                 "commit-transition", str(plan_path),
                 "from_state=active", "new_state=closing:review",
                 f"event=work_{mode}"],
                workspace, dry_run=dry_run,
            )
            meta_state = "closing:review"
        except Exception:
            pass

    stale_done = workspace / ".close-progress.done"
    if stale_done.exists():
        stale_done.unlink()

    rec = lambda evt, **kw: _record(evt, branch, project, issue_repo, dry_run, **kw)

    if args.get("conflict_resolved") == "yes":
        conflict_repo = args.get("conflict_repo", "")
        progress_snapshot = read_close_progress(workspace)
        rebase_key = f"rebase:{conflict_repo}" if conflict_repo else "rebase"
        if progress_snapshot.get(rebase_key) == "done":
            step_key = f"land:{conflict_repo}" if conflict_repo else "land"
        else:
            step_key = rebase_key
        update_close_progress(workspace, step_key, "done")

    if args.get("force_done"):
        step_name = args["force_done"]
        if step_name == "verify":
            progress_snapshot = read_close_progress(workspace)
            if progress_snapshot.get("_blocking_fail") == "yes":
                return {
                    "ACTION": "error",
                    "ERROR": "BLOCKING_VERIFICATION_FAILURE",
                    "STEP": "verify",
                    "REASON": progress_snapshot.get("_blocking_detail", "blocking checks failed — cannot force"),
                }
            update_close_progress(workspace, "_final_gate_forced", "yes")
        update_close_progress(workspace, step_name, "done")
        if args.get("produced"):
            update_close_progress(workspace, f"{step_name}_produced", args["produced"])
        last = read_close_progress(workspace).get("last_yielded", "")
        if last == step_name:
            update_close_progress(workspace, "last_yielded", "")

    if args.get("skip_user_input_steps") == "yes":
        for ui_step in CLOSE_USER_INPUT_STEPS:
            update_close_progress(workspace, ui_step, "done")

    if args.get("step_done"):
        step_name = args["step_done"]
        if step_name == "queue_decision" and args.get("produced") == "sync":
            delete_close_progress(workspace)
            return {
                "ACTION": "redirect_sync",
                "REASON": "User chose work sync — rerun with mode=sync",
            }
        if step_name == "sweep_config":
            return {
                "ACTION": "error",
                "ERROR": "invalid_step_done",
                "STEP": "sweep_config",
                "REASON": "Use sweep_selected= to complete sweep_config",
            }

        from judgment import parse_response, validate_response, Outcome, DEFAULT_JUDGMENT_SCHEMA
        try:
            response = parse_response(args)
        except ValueError as e:
            rec("invalid-outcome", step=step_name, reason=str(e))
            return {"ACTION": "error", "ERROR": "invalid_outcome",
                    "STEP": step_name, "DETAIL": str(e)}

        step_def = next((s for s in STEPS if s.name == step_name), None)
        if step_def:
            schema = step_def.response_schema or DEFAULT_JUDGMENT_SCHEMA
            errors = validate_response(response, schema)
            if errors:
                rec("schema-violation", step=step_name, reason="; ".join(errors))
                return {"ACTION": "error", "ERROR": "schema_violation",
                        "STEP": step_name, "DETAIL": "; ".join(errors)}

        if response.outcome == Outcome.SKIPPED:
            err = validate_skip(workspace, step_name)
            if err:
                rec("invalid-skip", step=step_name, reason=err.get("REASON", ""))
                return err
        elif response.outcome == Outcome.BLOCKED:
            rec("step-blocked", step=step_name, reason=response.block_reason or "")
            return {"ACTION": "error", "ERROR": "step_blocked",
                    "STEP": step_name, "REASON": response.block_reason or "no reason"}
        else:
            if step_def and step_def.verify_fn:
                verify_error = step_def.verify_fn(workspace, args.get("produced"), branch=branch)
                if verify_error:
                    rec("postcondition-failed", step=step_name, reason=verify_error)
                    return {
                        "ACTION": "error",
                        "ERROR": "postcondition_failed",
                        "STEP": step_name,
                        "REASON": verify_error,
                    }
            err = apply_step_done(workspace, args["step_done"], args.get("produced"),
                                  mechanical_steps=MECHANICAL_STEPS)
            if err:
                rec("invalid-step-done", step=args["step_done"], reason=err.get("REASON", ""))
                return err

    if args.get("sweep_selected") is not None:
        selected = args["sweep_selected"]
        update_close_progress(workspace, "sweep_config", "done")
        update_close_progress(workspace, "sweep_selected", selected)

    progress = Progress.load(workspace)

    if progress and progress.get("_branch") and progress["_branch"] != branch:
        rec("branch-mismatch-reset", stale_branch=progress["_branch"])
        delete_close_progress(workspace)
        progress = Progress()

    if not progress.get("_branch") and branch:
        update_close_progress(workspace, "_branch", branch)
        progress["_branch"] = branch

    if progress.get("review") == "done" and "code_review" not in progress:
        for sub in REVIEW_SUB_STEPS:
            progress[sub] = "done"
        write_close_progress(workspace, progress)

    if is_stale(progress, meta_state, plan_path=plan_path,
                project=project, branch=branch):
        rec("stale-progress-reset", meta_state=meta_state,
            progress_keys=",".join(progress.keys()))
        delete_close_progress(workspace)
        progress = Progress()
    elif progress:
        reconciled, corrections = _reconcile(workspace, project, progress, meta_state)
        if corrections:
            rec("reconciliation-correction", meta_state=meta_state,
                corrected_steps=",".join(corrections))
            write_close_progress(workspace, reconciled)
            progress = Progress.from_dict(reconciled)

    _slot_info = _parse_slot(slot_path) if in_slot and slot_path else None
    slot_repos = _slot_info.repos if _slot_info else []

    from repo_state import classify_repos as _classify_repos, build_repo_contexts as _build_repo_contexts
    _raw_repos = _classify_repos(
        project=project,
        workspace=workspace,
        branch=branch,
        base_branch=base_branch,
        slot_path=slot_path if in_slot else None,
    )

    _wl_conn = None
    _wl_wid = None
    if _wl:
        try:
            _wl_conn = _wl.connect()
            _wl_wid = _wl.find_work_item(_wl_conn, branch, str(project))
        except Exception:
            _wl_conn = None

    repos = _build_repo_contexts(_raw_repos, base_branch, _wl_conn, _wl_wid)

    if _wl_conn:
        try:
            _wl_conn.close()
        except Exception:
            pass

    if plan_path and plan_path.exists():
        from close_progress import _read_plan_state, LIFECYCLE_PHASE_ORDER
        actual = _read_plan_state(plan_path)
        if actual and actual in LIFECYCLE_PHASE_ORDER:
            if actual != meta_state:
                rec("meta-state-corrected", passed=meta_state, disk=actual)
                meta_state = actual
    phase_skip_state = meta_state
    progress = _phase_skip(progress, phase_skip_state, workspace,
                           slot_repos=slot_repos or None)

    p_mode = determine_pipeline_mode(
        on_main=on_main, in_slot=in_slot, mode=mode,
        workspace=workspace, covers=covers, issue_repo=issue_repo,
    )

    if not repos and p_mode != PipelineMode.MAIN:
        rec("empty-repos-warning", mode=p_mode.value,
            path=str(slot_path or project))

    ctx = OrchestratorContext(
        workspace=workspace, project=project, branch=branch,
        base_branch=base_branch, meta_state=meta_state,
        on_main=on_main, in_slot=in_slot, covers=covers,
        issue_repo=issue_repo, progress=progress,
        dry_run=dry_run, call_log=[],
        plan_path=plan_path, slot_path=slot_path,
        family_root=family_root, slot_num=slot_num,
        mode=mode, pipeline_mode=p_mode,
        expected_state=meta_state,
        slot_repos=slot_repos,
        repos=repos,
    )
    _hydrate_landed_shas(ctx)

    result = _next_action(ctx)
    if ctx.expected_state and ctx.expected_state != meta_state:
        if mode == "end" and meta_state.startswith("closing:") and ctx.expected_state == "active":
            pass
        else:
            result["META_STATE"] = ctx.expected_state
    _log_call(workspace, meta_state, result, ctx.steps_executed, dry_run=dry_run)

    if result.get("ERROR") and not dry_run:
        rec(f"step-error", step=result.get("STEP", ""),
            error=result.get("ERROR", ""), retry=result.get("RETRY", ""))

    if result.get("CONTEXT") == "step_failed":
        rec("step-failed", step=result.get("STEP", ""),
            attempts=int(result.get("ATTEMPTS", "0")),
            reason=result.get("REASON", ""))

    if result.get("ACTION") == "complete":
        from progress_summary import format_summary
        final_progress = getattr(ctx, "final_progress", None) or read_close_progress(workspace)
        if final_progress:
            result["REPORT"] = format_summary(final_progress, "close",
                                              workspace=workspace,
                                              branch=branch)

        if _wl and not dry_run:
            try:
                conn = _wl.connect()
                steps_data = _build_close_step_outcomes(progress)
                _wl.record_session_boundary(
                    conn, mode="close", branch=branch,
                    issue_repo=issue_repo,
                    issue_number=parse_covers(covers)[0] if covers else 0,
                    steps=steps_data,
                )
                conn.close()
            except Exception:
                pass

    return result


def _handle_abort(workspace: Path, meta_state: str) -> dict[str, str]:
    if meta_state in ABORTABLE_STATES:
        delete_close_progress(workspace)
        exec_progress = workspace / ".execute-progress"
        if exec_progress.exists():
            exec_progress.unlink()
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


def _close_execute_mechanical(step: StepDef, ctx: OrchestratorContext) -> dict[str, str]:
    """Work-end-specific mechanical execution with main-mode overrides."""
    if step.name == "delete_progress":
        ctx.final_progress = dict(read_close_progress(ctx.workspace))
        if not ctx.dry_run:
            _cleanup_close_artifacts(ctx.workspace)
        elif ctx.call_log is not None:
            ctx.call_log.append(["(internal)", "delete_progress"])
        return {"DELETED": "yes"}

    if not step.script_fn:
        return {}

    cmd = step.script_fn(ctx)
    if cmd is None:
        if step.name == "elevate_plan" and ctx.in_slot:
            return _elevate_plan_inline(ctx)
        if step.name == "land" and ctx.on_main:
            return _push_main_mode(ctx)
        if step.name == "verify" and ctx.on_main:
            return _verify_main_mode(ctx)
        if step.name == "cleanup" and ctx.on_main:
            return _cleanup_main_mode(ctx)
        return {}
    return _run_script(cmd, ctx.workspace, dry_run=ctx.dry_run, call_log=ctx.call_log)


def _persist_landed_shas(ctx: OrchestratorContext) -> None:
    """Write landed_shas to .close-progress so they survive re-invocation."""
    for repo, sha in ctx.landed_shas.items():
        if sha:
            update_close_progress(ctx.workspace, f"_landed_sha:{repo}", sha)


def _hydrate_landed_shas(ctx: OrchestratorContext) -> None:
    """Restore landed_shas from _landed_sha:* entries in progress."""
    prefix = "_landed_sha:"
    for key, value in ctx.progress.items():
        if key.startswith(prefix) and value:
            repo = key[len(prefix):]
            ctx.landed_shas[repo] = value


def _close_on_step_done(step: StepDef, ctx: OrchestratorContext, result: dict[str, str]) -> None:
    """Track landed SHAs, fork branch, and blocking failures after relevant steps complete."""
    if step.name == "land":
        ctx.landed_shas = _parse_landed_shas(result, ctx)
        _persist_landed_shas(ctx)
    if step.name == "fork_next_branch":
        fork_branch = result.get("FORK_BRANCH", "")
        if fork_branch:
            update_close_progress(ctx.workspace, "fork_next_branch", fork_branch)
    if step.name == "verify":
        if result.get("BLOCKING_FAIL") == "yes":
            update_close_progress(ctx.workspace, "_blocking_fail", "yes")
            update_close_progress(ctx.workspace, "_blocking_detail",
                                  result.get("BLOCKING_DETAIL", ""))


def _close_per_repo_mechanical(step: StepDef, ctx: OrchestratorContext) -> dict[str, str] | None:
    """Per-repo fan-out for slot-mode mechanical steps.

    Tries ALL remaining repos before reporting. Successful repos are
    marked done immediately. Failures are collected and returned as a
    consolidated report so the user sees the full picture.
    """
    if step.name not in PER_REPO_EXECUTE_STEPS or not ctx.in_slot:
        return None
    if not ctx.repos:
        return None
    if ctx.per_repo_done(step.name):
        return {}

    failures: dict[str, dict[str, str]] = {}
    retryable_failure: tuple[str, int, dict[str, str]] | None = None

    for item in ctx.repos:
        repo_name = item.state.name
        repo_path = item.state.path

        step_key = f"{step.name}:{repo_name}"
        if ctx.progress.get(step_key) in ("done", "skipped", "skipped_error"):
            continue

        if step.name == "rebase" and item.state.disposition in (
            RepoDisposition.NO_BRANCH, RepoDisposition.ALREADY_LANDED,
        ):
            update_close_progress(ctx.workspace, step_key, "done")
            ctx.steps_executed.append(f"{step_key}:skipped_by_disposition")
            continue

        if step.name == "land" and item.state.disposition in (
            RepoDisposition.NO_BRANCH, RepoDisposition.EMPTY_BRANCH,
            RepoDisposition.ALREADY_LANDED,
        ):
            update_close_progress(ctx.workspace, step_key, "done")
            ctx.steps_executed.append(f"{step_key}:skipped_by_disposition")
            continue

        ctx.current_repo_project = repo_path
        ctx.current_repo_workspace = _resolve_repo_workspace(ctx, repo_name)
        result = _close_execute_mechanical(step, ctx)
        ctx.current_repo_project = None
        ctx.current_repo_workspace = None

        if result and "ERROR" in result:
            error = result.get("ERROR", "")
            if error in NON_RETRYABLE_ERRORS:
                failures[repo_name] = result
                ctx.steps_executed.append(f"{step_key}:ERROR:classified")
            else:
                attempt_key = f"{step_key}_mechanical_attempt"
                raw_attempt = ctx.progress.get(attempt_key, "0")
                try:
                    attempt = int(raw_attempt) + 1
                except (ValueError, TypeError):
                    attempt = 1
                update_close_progress(ctx.workspace, attempt_key, str(attempt))
                ctx.steps_executed.append(f"{step_key}:ERROR:{attempt}")
                if retryable_failure is None:
                    retryable_failure = (step_key, attempt, result)
        else:
            ctx.last_output = result or {}
            if step.name == "land":
                sha = (result or {}).get("LANDED_SHA", "")
                ctx.landed_shas[repo_name] = sha
                if sha:
                    update_close_progress(ctx.workspace, f"_landed_sha:{repo_name}", sha)
            update_close_progress(ctx.workspace, step_key, "done")
            ctx.steps_executed.append(step_key)

    if failures:
        context: dict[str, str] = {
            "ACTION": "user_input",
            "CONTEXT": "per_repo_failures",
            "STEP": step.name,
            "FAILED_REPOS": ",".join(failures.keys()),
        }
        for repo, result in failures.items():
            context[f"ERROR_{repo}"] = result.get("ERROR", "unknown")
            context[f"DETAIL_{repo}"] = result.get("ERROR_DETAIL", "")
            if result.get("CONFLICT_COUNT"):
                context[f"CONFLICTS_{repo}"] = result.get("CONFLICT_COUNT", "")
            context[f"FORCE_DONE_HINT_{repo}"] = f"force_done={step.name}:{repo}"
        return context

    if retryable_failure:
        step_key, attempt, result = retryable_failure
        if attempt >= MAX_MECHANICAL_RETRIES:
            update_close_progress(ctx.workspace, step_key, "skipped_error")
            ctx.steps_executed.append(f"{step_key}:SKIPPED_ERROR")
        else:
            from orchestrator_engine import _make_error_result
            return _make_error_result(step_key, attempt, result)

    return {}


def _close_per_repo_judgment(step: StepDef, ctx: OrchestratorContext) -> dict[str, str] | None:
    """Per-repo fan-out for slot-mode judgment steps."""
    if step.name not in PER_REPO_SWEEP_STEPS or not ctx.in_slot or not ctx.slot_repos:
        return None
    if ctx.repos:
        changed_repos = {r.state.name for r in ctx.repos
                         if r.state.disposition == RepoDisposition.HAS_WORK}
        for repo_name in ctx.slot_repos:
            step_key = f"{step.name}:{repo_name}"
            if repo_name not in changed_repos:
                if ctx.progress.get(step_key) not in ("done", "skipped", "skipped_error"):
                    update_close_progress(ctx.workspace, step_key, "done")
                    ctx.progress.set(step_key, "done")
    if ctx.per_repo_done(step.name):
        return {}
    repo = ctx.next_repo_for(step.name)
    if not repo:
        return {}
    repo_path = str(ctx.slot_path / repo)
    context = {"REPO": repo_path}
    if step.action_context_fn:
        context.update(step.action_context_fn(ctx))
    from orchestrator_engine import _yield_judgment
    from judgment import JudgmentRequest, DEFAULT_JUDGMENT_SCHEMA
    request = JudgmentRequest(
        step=f"{step.name}:{repo}",
        handler=step.handler,
        context=context,
        response_schema=step.response_schema or DEFAULT_JUDGMENT_SCHEMA,
        skippable=step.skippable,
        timeout_hint=step.timeout_hint,
    )
    return _yield_judgment(request, ctx.workspace, ctx.progress)


def _parse_landed_shas(result: dict[str, str], ctx: OrchestratorContext) -> dict[str, str]:
    if ctx.in_slot:
        raw = result.get("LANDED_SHAS", "")
        return dict(pair.split(":") for pair in raw.split(",") if ":" in pair)
    sha = result.get("LANDED_SHA", "")
    if sha:
        return {ctx.project.name: sha}
    return {}


CLOSE_USER_INPUT_STEPS = {"arc42_scan", "session_rename", "garden_feedback", "notes"}

NON_RETRYABLE_ERRORS = {"REBASE_CONFLICT", "DIRTY_WORKTREE", "no_report", "BLOCKING_VERIFICATION_FAILURE"}


def _close_mechanical_error(step: StepDef, ctx: OrchestratorContext,
                            result: dict[str, str]) -> dict[str, str] | None:
    error = result.get("ERROR", "")
    if error not in NON_RETRYABLE_ERRORS:
        return None
    context = {"CONTEXT": f"{error.lower()}", "STEP": step.name}
    context["FORCE_DONE_HINT"] = f"force_done={step.name}"
    context.update(result)
    return {"ACTION": "user_input", **context}


MAX_FINAL_GATE_ATTEMPTS = 3


def _final_gate(ctx: OrchestratorContext) -> dict[str, str] | None:
    """Verify before ACTION=complete. Runs the verify script mechanically.
    Skipped in sync mode (branch stays open) and when force_done=verify was passed."""
    if ctx.on_main or ctx.dry_run or ctx.mode == "sync":
        return None
    if ctx.progress.get("_final_gate_forced") == "yes":
        return None
    verify_step = next((s for s in STEPS if s.name == "verify"), None)
    if not verify_step or not verify_step.script_fn:
        return None
    cmd = verify_step.script_fn(ctx)
    if cmd is None:
        return None

    raw_gate = ctx.progress.get("_final_gate_attempt", "0")
    try:
        attempt = int(raw_gate) + 1
    except (ValueError, TypeError):
        attempt = 1
    update_close_progress(ctx.workspace, "_final_gate_attempt", str(attempt))

    result = _run_script(cmd, ctx.workspace, dry_run=False, call_log=ctx.call_log)
    if result.get("VERIFIED") == "yes":
        return None
    failures = []
    for k, v in result.items():
        if k.startswith("FAILURE_") or (isinstance(v, str) and "fail" in v.lower()):
            failures.append(f"{k}={v}")
    failure_str = "; ".join(failures) if failures else "final gate verify failed"

    if attempt >= MAX_FINAL_GATE_ATTEMPTS:
        return {
            "ACTION": "user_input",
            "CONTEXT": "final-gate-exhausted",
            "VERIFIED": "no",
            "FAILURES": failure_str,
            "ATTEMPTS": str(attempt),
            "REASON": (f"Final gate failed {attempt} times. "
                       "Manual intervention required — verify and resolve, "
                       "then pass force_done=verify to continue."),
        }

    return {
        "ACTION": "verify_recover",
        "VERIFIED": "no",
        "FAILURES": failure_str,
        "ATTEMPT": str(attempt),
        "MAX_ATTEMPTS": str(MAX_FINAL_GATE_ATTEMPTS),
        "FORCE_DONE_HINT": "force_done=verify",
        "REASON": "final-gate: landing must be verified before close completes",
    }


def _next_action(ctx: OrchestratorContext) -> dict[str, str]:
    return run_loop(
        STEPS, ctx,
        execute_mechanical_fn=_close_execute_mechanical,
        on_step_done=_close_on_step_done,
        handle_lifecycle=_fire_lifecycle,
        per_repo_mechanical=_close_per_repo_mechanical,
        per_repo_judgment=_close_per_repo_judgment,
        on_mechanical_error=_close_mechanical_error,
        user_input_steps=CLOSE_USER_INPUT_STEPS,
        complete_summary="Close complete.",
        final_gate_fn=_final_gate,
    )


def _sweep_defaults() -> str:
    return ",".join(f"{s}:on" for s in SWEEP_STEPS)


def _get_sweep_selected(progress: dict[str, str]) -> set[str]:
    raw = progress.get("sweep_selected", "")
    if not raw:
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}


def _build_close_step_outcomes(progress: dict[str, str]) -> dict:
    """Build step outcomes from progress for the session boundary event."""
    outcomes = {}
    for step_name in ["review", "forage", "protocol", "update_claude_md",
                      "impl_doc_sync", "adr", "write_content",
                      "garden_feedback", "notes", "promote", "rebase",
                      "squash", "land", "close_issues", "verify",
                      "arc42_scan", "trajectory", "session_rename"]:
        status = progress.get(step_name)
        if status == "done":
            raw_produced = progress.get(f"{step_name}_produced", "0")
            try:
                produced = int(raw_produced)
            except (ValueError, TypeError):
                produced = 0
            outcomes[step_name] = {"ran": True, "produced": produced}
        elif status == "skipped":
            outcomes[step_name] = {"ran": False, "skipped": True}
    return outcomes


def main():
    args = parse_args(sys.argv[1:])
    required = ["workspace", "branch", "meta_state"]
    for key in required:
        if key not in args:
            print(f"ERROR=missing_arg ARG={key}")
            sys.exit(1)

    result = run_orchestrator(args)
    report = result.pop("REPORT", None)
    for k, v in result.items():
        print(f"{k}={v}")
    if report:
        print()
        print(report)


if __name__ == "__main__":
    main()
