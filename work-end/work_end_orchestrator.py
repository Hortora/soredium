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
        [sweep_selected=<csv>] [skip_step=<name>] \
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

CLOSE_LOG_FILE = ".close-log.jsonl"
CLOSE_FILES_TO_EXCLUDE = [".close-progress", ".close-progress.tmp", ".close-progress.done",
                          ".close-log.jsonl", ".close-report.json"]


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

ABORTABLE_STATES = {"closing:review", "closing:verified"}


from orchestrator_engine import run_script as _run_script, run_loop, log_call as _engine_log_call, validate_skip, apply_step_done

MECHANICAL_STEPS = None  # populated after STEPS is defined

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
from plan_io import parse_covers


def _parse_slot_repos(slot_path: Path) -> list[str]:
    if not slot_path or not slot_path.is_dir():
        return []

    primary = None
    secondaries_from_file = []
    slot_file = slot_path / ".slot"
    if slot_file.exists():
        in_repos = False
        for line in slot_file.read_text().splitlines():
            if line.strip() == "## Repos":
                in_repos = True
                continue
            if in_repos:
                if line.startswith("##"):
                    break
                stripped = line.strip()
                if stripped.startswith("- "):
                    is_primary = "(primary)" in stripped
                    name = stripped[2:].split("(")[0].strip()
                    if is_primary:
                        primary = name
                    else:
                        secondaries_from_file.append(name)

    file_repos = set()
    if primary:
        file_repos.add(primary)
    file_repos.update(secondaries_from_file)

    dir_repos = set()
    skip_prefixes = ("wsp-", ".m2", "attic")
    for entry in sorted(slot_path.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        if any(entry.name.startswith(p) for p in skip_prefixes):
            continue
        dir_repos.add(entry.name)

    extra = sorted(dir_repos - file_repos)
    if primary:
        return [primary] + [s for s in secondaries_from_file if s in dir_repos] + extra
    return sorted(dir_repos)


PER_REPO_SWEEP_STEPS = {"protocol", "update_claude_md", "impl_doc_sync", "doc_freshness_gate"}
PER_REPO_EXECUTE_STEPS = {"promote", "rebase", "land"}


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
    progress: dict[str, str]
    dry_run: bool = False
    call_log: list = field(default_factory=list)
    plan_path: Path | None = None
    slot_path: Path | None = None
    family_root: Path | None = None
    slot_num: str = ""
    last_output: dict[str, str] = field(default_factory=dict)
    landed_shas: dict[str, str] = field(default_factory=dict)
    expected_state: str = ""
    slot_repos: list[str] = field(default_factory=list)
    steps_executed: list[str] = field(default_factory=list)
    current_repo_project: Path | None = None
    current_repo_workspace: Path | None = None

    def done(self, step: str) -> bool:
        return self.progress.get(step) in ("done", "skipped")

    def per_repo_done(self, step: str) -> bool:
        if not self.in_slot or not self.slot_repos:
            return self.done(step)
        return all(self.progress.get(f"{step}:{repo}") in ("done", "skipped") for repo in self.slot_repos)

    def next_repo_for(self, step: str) -> str | None:
        if not self.in_slot or not self.slot_repos:
            return None
        for repo in self.slot_repos:
            if self.progress.get(f"{step}:{repo}") not in ("done", "skipped"):
                return repo
        return None


@dataclass
class StepDef:
    name: str
    phase: str
    step_type: str
    script_fn: Callable | None = None
    skip_fn: Callable | None = None
    action_context_fn: Callable | None = None
    verify_fn: Callable | None = None
    from_state: str | None = None
    to_state: str | None = None
    event: str | None = None


# --- Skip predicates ---

def _skip_on_main(ctx: OrchestratorContext) -> bool:
    return ctx.on_main


def _skip_not_main(ctx: OrchestratorContext) -> bool:
    return not ctx.on_main


def _skip_not_slot(ctx: OrchestratorContext) -> bool:
    return not ctx.in_slot


def _skip_no_covers(ctx: OrchestratorContext) -> bool:
    return not ctx.covers


def _skip_no_upstream(ctx: OrchestratorContext) -> bool:
    result = subprocess.run(
        ["git", "-C", str(ctx.project), "remote", "get-url", "upstream"],
        capture_output=True, text=True,
    )
    return result.returncode != 0


def _upstream_pr_context(ctx: OrchestratorContext) -> dict[str, str]:
    base = ctx.base_branch
    fork_ahead = 0
    upstream_ahead = 0
    proc = subprocess.run(
        ["git", "-C", str(ctx.project), "rev-list", "--count", f"upstream/{base}..origin/{base}"],
        capture_output=True, text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        fork_ahead = int(proc.stdout.strip())
    proc = subprocess.run(
        ["git", "-C", str(ctx.project), "rev-list", "--count", f"origin/{base}..upstream/{base}"],
        capture_output=True, text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        upstream_ahead = int(proc.stdout.strip())
    upstream_url = ""
    proc = subprocess.run(
        ["git", "-C", str(ctx.project), "remote", "get-url", "upstream"],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        upstream_url = proc.stdout.strip()
    return {
        "FORK_AHEAD": str(fork_ahead),
        "UPSTREAM_AHEAD": str(upstream_ahead),
        "UPSTREAM_URL": upstream_url,
    }


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
    ws = ctx.current_repo_workspace or ctx.workspace
    proj = ctx.current_repo_project or ctx.project
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
            from plan_manager import get_completed_epic_parents
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


def _report_archive_script(ctx):
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            "step=archive", f"slot={ctx.slot_num or ''}", f"dest=attic/{ctx.slot_num or ''}"]


def _checkout_main_script(ctx):
    return [sys.executable, str(CLEANUP_SCRIPT),
            "checkout-main", str(ctx.project), str(ctx.workspace)]


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


def _archive_close_progress(workspace: Path) -> None:
    src = workspace / ".close-progress"
    dst = workspace / ".close-progress.done"
    if src.exists():
        os.replace(src, dst)
    tmp = workspace / ".close-progress.tmp"
    if tmp.exists():
        tmp.unlink()


# --- Main-mode special cases ---

def _push_main_mode(ctx):
    if ctx.dry_run:
        if ctx.call_log is not None:
            ctx.call_log.append(["(internal)", "push_main_mode", f"project={ctx.project}", f"workspace={ctx.workspace}"])
        return {"PUSHED": "yes", "LANDED_SHA": "dry_run"}
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
        return
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
    _run_script(cmd, ctx.workspace, dry_run=ctx.dry_run, call_log=ctx.call_log)


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
    stack_file = ws / ".pause-stack"
    if not stack_file.exists():
        return True
    return True


EVIDENCE_CHECKS: dict[str, Callable] = {
    "land": lambda ws, proj: (ws / ".execute-progress").exists(),
    "rebase": _check_rebase,
    "close_issues": lambda ws, proj: True,
    "verify": lambda ws, proj: True,
    "cleanup": lambda ws, proj: not (ws / "JOURNAL.md").exists() or (ws / ".plan").exists(),
    "checkout_main": _check_checkout_main,
    "cleanup_stack": _check_cleanup_stack,
    "promote": lambda ws, proj: True,
    "archive_slot": lambda ws, proj: True,
}
JUDGMENT_STEPS_SET = {"code_review", "branch_audit_conformance",
                      "branch_audit_coherence", "branch_audit_structure",
                      "branch_audit_robustness", "loose_ends", "forcing_function",
                      "sweep_config", "forage", "protocol",
                      "update_claude_md", "impl_doc_sync", "doc_freshness_gate", "adr",
                      "write_content", "trajectory", "squash",
                      "upstream_pr",
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
    filled = False
    for step_def in STEPS:
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
        if step.startswith("report_") or step.startswith("fallback_"):
            continue
        if "_attempt" in step or step == "sweep_selected":
            continue
        if step in JUDGMENT_STEPS_SET:
            continue
        step_phase = STEP_TO_PHASE.get(step, "closing:review")
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
    }


def _forcing_function_context(ctx):
    findings_path = ctx.workspace / ".audit" / "findings.jsonl"
    count = 0
    if findings_path.exists():
        for line in findings_path.read_text().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("status", "open") == "open":
                    count += 1
            except (json.JSONDecodeError, ValueError):
                pass
    return {"CONTEXT": "forcing_function", "OPEN_FINDINGS": str(count)}


# --- Verify functions (postcondition checks) ---

def _verify_produced_required(workspace: Path, produced: str | None) -> str | None:
    if produced is None:
        return "produced count required — retry with: step_done=<STEP> produced=N (use 0 if no findings)"
    return None


def _verify_squash(workspace: Path, produced: str | None) -> str | None:
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


def _verify_forcing_function(workspace: Path, produced: str | None) -> str | None:
    findings_path = workspace / ".audit" / "findings.jsonl"
    if not findings_path.exists():
        return None
    _project = Path(__file__).resolve().parent.parent / "project"
    sys.path.insert(0, str(_project))
    try:
        from findings import read_findings
        findings = read_findings(findings_path)
        open_findings = [f for f in findings if f.get("status", "open") == "open"]
        if open_findings:
            details = "; ".join(f.get("detail", "?")[:40] for f in open_findings[:3])
            return f"{len(open_findings)} open finding(s): {details}"
    except ImportError:
        pass
    return None


STEPS: list[StepDef] = [
    # --- closing:review (sub-steps) ---
    StepDef("report_init", "closing:review", "mechanical",
            script_fn=_report_init_script),
    StepDef("code_review", "closing:review", "judgment",
            action_context_fn=_diff_range_context,
            verify_fn=_verify_produced_required),
    StepDef("branch_audit_conformance", "closing:review", "judgment",
            action_context_fn=_dimension_context("conformance"),
            verify_fn=_verify_produced_required),
    StepDef("branch_audit_coherence", "closing:review", "judgment",
            action_context_fn=_dimension_context("coherence"),
            verify_fn=_verify_produced_required),
    StepDef("branch_audit_structure", "closing:review", "judgment",
            action_context_fn=_dimension_context("structure"),
            verify_fn=_verify_produced_required),
    StepDef("branch_audit_robustness", "closing:review", "judgment",
            action_context_fn=_dimension_context("robustness"),
            verify_fn=_verify_produced_required),
    StepDef("loose_ends", "closing:review", "judgment",
            action_context_fn=_loose_ends_context,
            verify_fn=_verify_produced_required),
    StepDef("forcing_function", "closing:review", "judgment",
            action_context_fn=_forcing_function_context,
            verify_fn=_verify_forcing_function),
    StepDef("sweep_config", "closing:review", "judgment",
            action_context_fn=lambda ctx: {"ITEMS": _sweep_defaults()}),
    StepDef("forage", "closing:review", "judgment",
            skip_fn=_is_sweep_deselected("forage")),
    StepDef("protocol", "closing:review", "judgment",
            skip_fn=_is_sweep_deselected("protocol")),
    StepDef("update_claude_md", "closing:review", "judgment",
            skip_fn=_is_sweep_deselected("update_claude_md")),
    StepDef("impl_doc_sync", "closing:review", "judgment",
            skip_fn=_is_sweep_deselected("impl_doc_sync")),
    StepDef("doc_freshness_gate", "closing:review", "judgment",
            skip_fn=_is_sweep_deselected("doc_freshness_gate")),
    StepDef("adr", "closing:review", "judgment",
            skip_fn=_is_sweep_deselected("adr")),
    StepDef("write_content", "closing:review", "judgment",
            skip_fn=_is_sweep_deselected("write_content")),

    # --- lifecycle: review -> verified ---
    StepDef("review_pass", "closing:review", "lifecycle",
            from_state="closing:review", to_state="closing:verified", event="review_pass"),

    # --- closing:verified ---
    StepDef("promote", "closing:verified", "mechanical",
            script_fn=_promote_script),
    StepDef("report_promote", "closing:verified", "mechanical",
            script_fn=_report_promote_script),
    StepDef("promote_pass", "closing:verified", "lifecycle",
            from_state="closing:verified", to_state="closing:promoted", event="promote_pass"),

    # --- closing:promoted ---
    StepDef("trajectory", "closing:promoted", "judgment",
            action_context_fn=lambda ctx: {"COVERS": ctx.covers, "OWNER_REPO": ctx.issue_repo}),
    StepDef("rebase", "closing:promoted", "mechanical",
            skip_fn=_skip_on_main,
            script_fn=_rebase_script),
    StepDef("report_rebase", "closing:promoted", "mechanical",
            skip_fn=_skip_on_main,
            script_fn=_report_rebase_script),
    StepDef("squash", "closing:promoted", "judgment",
            skip_fn=_skip_on_main,
            action_context_fn=lambda ctx: {"REPOS": ctx.project.name},
            verify_fn=_verify_squash),
    StepDef("report_squash", "closing:promoted", "mechanical",
            skip_fn=_skip_on_main,
            script_fn=_report_squash_script),
    StepDef("land", "closing:promoted", "mechanical",
            script_fn=_land_script),
    StepDef("report_land", "closing:promoted", "mechanical",
            script_fn=_report_land_script),
    StepDef("push_pass", "closing:promoted", "lifecycle",
            from_state="closing:promoted", to_state="closing:pushed", event="push_pass"),
    StepDef("merge_pass", "closing:pushed", "lifecycle",
            from_state="closing:pushed", to_state="closing:merged", event="merge_pass"),
    StepDef("stamp_pass", "closing:merged", "lifecycle",
            from_state="closing:merged", to_state="closing:stamped", event="stamp_pass"),

    # --- closing:stamped ---
    StepDef("write_landed", "closing:stamped", "mechanical",
            skip_fn=_skip_not_slot,
            script_fn=_write_landed_script),
    StepDef("close_issues", "closing:stamped", "mechanical",
            skip_fn=_skip_no_covers,
            script_fn=_close_issues_script),
    StepDef("report_close_issues", "closing:stamped", "mechanical",
            skip_fn=_skip_no_covers,
            script_fn=_report_close_issues_script),
    StepDef("verify", "closing:stamped", "mechanical",
            script_fn=_verify_script),
    StepDef("report_verify", "closing:stamped", "mechanical",
            script_fn=_report_verify_script),
    StepDef("archive_slot", "closing:stamped", "mechanical",
            skip_fn=_skip_not_slot,
            script_fn=_archive_slot_script),
    StepDef("report_archive", "closing:stamped", "mechanical",
            skip_fn=_skip_not_slot,
            script_fn=_report_archive_script),
    StepDef("checkout_main", "closing:stamped", "mechanical",
            skip_fn=_skip_on_main,
            script_fn=_checkout_main_script),
    StepDef("cleanup_stack", "closing:stamped", "mechanical",
            skip_fn=_skip_on_main,
            script_fn=_cleanup_stack_script),
    StepDef("cleanup", "closing:stamped", "mechanical",
            script_fn=_cleanup_scaffold_script),
    StepDef("report_scaffold", "closing:stamped", "mechanical",
            script_fn=_report_scaffold_script),
    StepDef("upstream_pr", "closing:stamped", "judgment",
            skip_fn=_skip_no_upstream,
            action_context_fn=_upstream_pr_context),
    StepDef("arc42_scan", "closing:stamped", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "arc42_scan"}),
    StepDef("session_rename", "closing:stamped", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "session_rename"}),
    StepDef("garden_feedback", "closing:stamped", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "garden_feedback"}),
    StepDef("notes", "closing:stamped", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "notes"}),

    # --- lifecycle: stamped -> idle/drained ---
    StepDef("cleanup_pass", "closing:stamped", "lifecycle",
            skip_fn=_skip_on_main,
            from_state="closing:stamped", to_state="idle", event="cleanup_pass"),
    StepDef("cleanup_main", "closing:stamped", "lifecycle",
            skip_fn=_skip_not_main,
            from_state="closing:stamped", to_state="drained", event="cleanup_main"),

    # --- post-close ---
    StepDef("delete_progress", "idle", "mechanical"),
    StepDef("report_render", "idle", "mechanical",
            script_fn=_report_render_script),
]

MECHANICAL_STEPS = {s.name for s in STEPS if s.step_type == "mechanical"}


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

    if args.get("abort") == "yes":
        return _handle_abort(workspace, meta_state)

    rec = lambda evt, **kw: _record(evt, branch, project, issue_repo, dry_run, **kw)

    if args.get("conflict_resolved") == "yes":
        conflict_repo = args.get("conflict_repo", "")
        step_key = f"rebase:{conflict_repo}" if conflict_repo else "rebase"
        update_close_progress(workspace, step_key, "done")

    if args.get("force_done"):
        step_name = args["force_done"]
        update_close_progress(workspace, step_name, "done")
        if args.get("produced"):
            update_close_progress(workspace, f"{step_name}_produced", args["produced"])
        last = read_close_progress(workspace).get("last_yielded", "")
        if last == step_name:
            update_close_progress(workspace, "last_yielded", "")

    if args.get("skip_step"):
        err = validate_skip(workspace, args["skip_step"])
        if err:
            rec("invalid-skip", step=args["skip_step"], reason=err.get("REASON", ""))
            return err

    if args.get("step_done"):
        step_name = args["step_done"]
        if step_name == "sweep_config":
            return {
                "ACTION": "error",
                "ERROR": "invalid_step_done",
                "STEP": "sweep_config",
                "REASON": "Use sweep_selected= to complete sweep_config",
            }
        step_def = next((s for s in STEPS if s.name == step_name), None)
        if step_def and step_def.verify_fn:
            verify_error = step_def.verify_fn(workspace, args.get("produced"))
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

    progress = read_close_progress(workspace)

    if progress and progress.get("_branch") and progress["_branch"] != branch:
        rec("branch-mismatch-reset", stale_branch=progress["_branch"])
        delete_close_progress(workspace)
        progress = {}

    if not progress.get("_branch") and branch:
        update_close_progress(workspace, "_branch", branch)
        progress["_branch"] = branch

    if progress.get("review") == "done" and "code_review" not in progress:
        for sub in REVIEW_SUB_STEPS:
            progress[sub] = "done"
        write_close_progress(workspace, progress)

    if is_stale(progress, meta_state, plan_path=plan_path):
        rec("stale-progress-reset", meta_state=meta_state,
            progress_keys=",".join(progress.keys()))
        delete_close_progress(workspace)
        progress = {}
    elif progress:
        progress, corrections = _reconcile(workspace, project, progress, meta_state)
        if corrections:
            rec("reconciliation-correction", meta_state=meta_state,
                corrected_steps=",".join(corrections))
            write_close_progress(workspace, progress)

    slot_repos = _parse_slot_repos(slot_path) if in_slot and slot_path else []

    progress = _phase_skip(progress, meta_state, workspace,
                           slot_repos=slot_repos or None)

    ctx = OrchestratorContext(
        workspace=workspace, project=project, branch=branch,
        base_branch=base_branch, meta_state=meta_state,
        on_main=on_main, in_slot=in_slot, covers=covers,
        issue_repo=issue_repo, progress=progress,
        dry_run=dry_run, call_log=[],
        plan_path=plan_path, slot_path=slot_path,
        family_root=family_root, slot_num=slot_num,
        expected_state=meta_state,
        slot_repos=slot_repos,
    )

    result = _next_action(ctx)
    if ctx.expected_state and ctx.expected_state != meta_state:
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
        done_path = workspace / ".close-progress.done"
        if done_path.exists():
            final_progress = {}
            for line in done_path.read_text().splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    final_progress[k.strip()] = v.strip()
        else:
            final_progress = read_close_progress(workspace)
        if final_progress:
            result["REPORT"] = format_summary(final_progress, "close",
                                              workspace=workspace)

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
        if not ctx.dry_run:
            _archive_close_progress(ctx.workspace)
        elif ctx.call_log is not None:
            ctx.call_log.append(["(internal)", "delete_progress"])
        return {"DELETED": "yes"}

    if not step.script_fn:
        return {}

    cmd = step.script_fn(ctx)
    if cmd is None:
        if step.name == "land" and ctx.on_main:
            return _push_main_mode(ctx)
        if step.name == "verify" and ctx.on_main:
            return _verify_main_mode(ctx)
        if step.name == "cleanup" and ctx.on_main:
            return _cleanup_main_mode(ctx)
        return {}
    return _run_script(cmd, ctx.workspace, dry_run=ctx.dry_run, call_log=ctx.call_log)


def _close_on_step_done(step: StepDef, ctx: OrchestratorContext, result: dict[str, str]) -> None:
    """Track landed SHAs after land step completes."""
    if step.name == "land":
        ctx.landed_shas = _parse_landed_shas(result, ctx)


def _close_per_repo_mechanical(step: StepDef, ctx: OrchestratorContext) -> dict[str, str] | None:
    """Per-repo fan-out for slot-mode mechanical steps.

    Tries ALL remaining repos before reporting. Successful repos are
    marked done immediately. Failures are collected and returned as a
    consolidated report so the user sees the full picture.
    """
    if step.name not in PER_REPO_EXECUTE_STEPS or not ctx.in_slot or not ctx.slot_repos:
        return None
    if ctx.per_repo_done(step.name):
        return {}

    failures: dict[str, dict[str, str]] = {}
    retryable_failure: tuple[str, int, dict[str, str]] | None = None

    for repo in ctx.slot_repos:
        step_key = f"{step.name}:{repo}"
        if ctx.progress.get(step_key) in ("done", "skipped"):
            continue

        ctx.current_repo_project = ctx.slot_path / repo if ctx.slot_path else None
        ctx.current_repo_workspace = _resolve_repo_workspace(ctx, repo)
        result = _close_execute_mechanical(step, ctx)
        ctx.current_repo_project = None
        ctx.current_repo_workspace = None

        if result and "ERROR" in result:
            error = result.get("ERROR", "")
            if error in NON_RETRYABLE_ERRORS:
                failures[repo] = result
                ctx.steps_executed.append(f"{step_key}:ERROR:classified")
            else:
                attempt_key = f"{step_key}_mechanical_attempt"
                attempt = int(ctx.progress.get(attempt_key, "0")) + 1
                update_close_progress(ctx.workspace, attempt_key, str(attempt))
                ctx.steps_executed.append(f"{step_key}:ERROR:{attempt}")
                if retryable_failure is None:
                    retryable_failure = (step_key, attempt, result)
        else:
            ctx.last_output = result or {}
            if step.name == "land":
                ctx.landed_shas[repo] = (result or {}).get("LANDED_SHA", "")
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
        return context

    if retryable_failure:
        step_key, attempt, result = retryable_failure
        from orchestrator_engine import _make_error_result
        return _make_error_result(step_key, attempt, result)

    return {}


def _close_per_repo_judgment(step: StepDef, ctx: OrchestratorContext) -> dict[str, str] | None:
    """Per-repo fan-out for slot-mode judgment steps."""
    if step.name not in PER_REPO_SWEEP_STEPS or not ctx.in_slot or not ctx.slot_repos:
        return None
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
    return _yield_judgment(f"{step.name}:{repo}", ctx.workspace, ctx.progress, context)


def _parse_landed_shas(result: dict[str, str], ctx: OrchestratorContext) -> dict[str, str]:
    if ctx.in_slot:
        raw = result.get("LANDED_SHAS", "")
        return dict(pair.split(":") for pair in raw.split(",") if ":" in pair)
    sha = result.get("LANDED_SHA", "")
    if sha:
        return {ctx.project.name: sha}
    return {}


CLOSE_USER_INPUT_STEPS = {"arc42_scan", "session_rename", "garden_feedback", "notes"}

NON_RETRYABLE_ERRORS = {"REBASE_CONFLICT"}


def _close_mechanical_error(step: StepDef, ctx: OrchestratorContext,
                            result: dict[str, str]) -> dict[str, str] | None:
    error = result.get("ERROR", "")
    if error not in NON_RETRYABLE_ERRORS:
        return None
    context = {"CONTEXT": f"{error.lower()}", "STEP": step.name}
    context.update(result)
    return {"ACTION": "user_input", **context}


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
            produced = int(progress.get(f"{step_name}_produced", "0"))
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
