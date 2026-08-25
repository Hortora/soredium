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


def _log_call(workspace: Path, meta_state: str, result: dict[str, str],
              steps_executed: list[str], dry_run: bool = False) -> None:
    if dry_run:
        return
    log_path = workspace / CLOSE_LOG_FILE
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "meta_state": meta_state,
        "action": result.get("ACTION", ""),
        "step": result.get("STEP", ""),
        "context": result.get("CONTEXT", ""),
        "steps_executed": steps_executed,
        "error": result.get("ERROR", ""),
    }
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


SWEEP_STEPS = ["forage", "protocol", "update_claude_md", "impl_doc_sync", "adr", "write_content"]

WORK_END_DIR = Path(__file__).parent

MAX_JUDGMENT_RETRIES = 3

ABORTABLE_STATES = {"closing:review", "closing:verified"}


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


def _parse_slot_repos(slot_path: Path) -> list[str]:
    slot_file = slot_path / ".slot" if slot_path else None
    if not slot_file or not slot_file.exists():
        return []
    primary = None
    secondaries = []
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
                    secondaries.append(name)
    if primary:
        return [primary] + secondaries
    return secondaries


PER_REPO_SWEEP_STEPS = {"protocol", "update_claude_md", "impl_doc_sync"}


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


def _is_sweep_deselected(step_name: str):
    def check(ctx: OrchestratorContext) -> bool:
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
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "promote", f"workspace={ctx.workspace}",
            f"project={ctx.project}", f"branch={ctx.branch}"]


def _report_promote_script(ctx):
    promoted = int(ctx.last_output.get("WORKSPACE_PROMOTED", 0)) + int(ctx.last_output.get("PROJECT_PROMOTED", 0))
    repos = f"{ctx.project.name},{ctx.workspace.name}"
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            f"step=promote", f"promoted_files={promoted}", f"target_repos={repos}"]


def _rebase_script(ctx):
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "rebase", f"project={ctx.project}", f"branch={ctx.branch}",
            f"base_branch={ctx.base_branch}"]


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
    if ctx.in_slot:
        return [sys.executable, str(SLOT_MANAGER),
                "merge-slot", str(ctx.slot_path)]
    if ctx.on_main:
        return None
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "land", f"project={ctx.project}", f"branch={ctx.branch}",
            f"base_branch={ctx.base_branch}", f"workspace={ctx.workspace}"]


def _report_land_script(ctx):
    sha = ctx.landed_shas.get(ctx.project.name, "")
    repos = ",".join(ctx.landed_shas.keys()) if ctx.landed_shas else ctx.project.name
    return [sys.executable, str(REPORT_SCRIPT), "record", str(_report_path(ctx)),
            f"step=land", f"landed_sha={sha}", f"pushed_repos={repos}"]


def _close_issues_script(ctx):
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "close-issues", f"repo={ctx.issue_repo}", f"covers={ctx.covers}"]


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
    return [sys.executable, str(CLEANUP_SCRIPT),
            "cleanup-scaffold", str(ctx.workspace)]


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
            ["git", "-C", str(repo_path), "push", "origin", "main"],
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
    subprocess.run(["git", "-C", str(ctx.workspace), "push"],
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
    ctx.expected_state = step.to_state


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
JUDGMENT_STEPS_SET = {"review", "sweep_config", "forage", "protocol",
                      "update_claude_md", "impl_doc_sync", "adr",
                      "write_content", "trajectory", "squash",
                      "arc42_scan", "session_rename", "garden_feedback", "notes"}


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

STEPS: list[StepDef] = [
    # --- closing:review ---
    StepDef("report_init", "closing:review", "mechanical",
            script_fn=_report_init_script),
    StepDef("review", "closing:review", "judgment",
            action_context_fn=lambda ctx: {"DIFF_RANGE": f"{ctx.base_branch}..{ctx.branch}"}),
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
            action_context_fn=lambda ctx: {"REPOS": ctx.project.name}),
    StepDef("report_squash", "closing:promoted", "mechanical",
            skip_fn=_skip_on_main,
            script_fn=_report_squash_script),
    StepDef("write_marker", "closing:promoted", "mechanical",
            skip_fn=_skip_not_slot,
            script_fn=_write_marker_script),
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

    if args.get("skip_step"):
        step = args["skip_step"]
        update_close_progress(workspace, step, "skipped")
        attempt_key = f"{step}_attempt"
        progress = read_close_progress(workspace)
        if attempt_key in progress:
            update_close_progress(workspace, attempt_key, "0")

    if args.get("sweep_selected") is not None and "sweep_config" in read_close_progress(workspace):
        selected = args["sweep_selected"]
        update_close_progress(workspace, "sweep_selected", selected)

    progress = read_close_progress(workspace)

    if is_stale(progress, meta_state):
        delete_close_progress(workspace)
        progress = {}
    elif progress:
        progress, corrections = _reconcile(workspace, project, progress, meta_state)
        if corrections:
            write_close_progress(workspace, progress)

    slot_repos = _parse_slot_repos(slot_path) if in_slot and slot_path else []

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
    _log_call(workspace, meta_state, result, ctx.steps_executed, dry_run=dry_run)
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


def _next_action(ctx: OrchestratorContext) -> dict[str, str]:
    for step in STEPS:
        if step.skip_fn and step.skip_fn(ctx):
            continue
        if ctx.done(step.name):
            continue

        if step.step_type == "mechanical":
            attempt_key = f"{step.name}_mechanical_attempt"
            attempt = int(ctx.progress.get(attempt_key, "0"))
            result = _execute_mechanical(step, ctx)
            if result and "ERROR" in result:
                attempt += 1
                update_close_progress(ctx.workspace, attempt_key, str(attempt))
                ctx.steps_executed.append(f"{step.name}:ERROR:{attempt}")
                if attempt >= 3:
                    return {
                        "ACTION": "user_input",
                        "CONTEXT": "step_failed",
                        "STEP": step.name,
                        "ATTEMPTS": str(attempt),
                        "REASON": result.get("ERROR", "unknown"),
                        "ERROR_DETAIL": result.get("ERROR_DETAIL", ""),
                    }
                return {"ACTION": "error", "STEP": step.name,
                        "RETRY": str(attempt), **result}
            ctx.last_output = result or {}
            if step.name == "land":
                ctx.landed_shas = _parse_landed_shas(ctx.last_output, ctx)
            update_close_progress(ctx.workspace, step.name, "done")
            ctx.steps_executed.append(step.name)
            continue

        if step.step_type == "judgment":
            if step.name in ("arc42_scan", "session_rename", "garden_feedback", "notes"):
                return _yield_user_input(step, ctx)
            if step.name in PER_REPO_SWEEP_STEPS and ctx.in_slot and ctx.slot_repos:
                if ctx.per_repo_done(step.name):
                    continue
                repo = ctx.next_repo_for(step.name)
                if repo:
                    repo_path = str(ctx.slot_path / repo)
                    context = {"REPO": repo_path}
                    if step.action_context_fn:
                        context.update(step.action_context_fn(ctx))
                    return _yield_judgment(f"{step.name}:{repo}", ctx.workspace, ctx.progress, context)
                continue
            return _yield_judgment(step.name, ctx.workspace, ctx.progress,
                                   step.action_context_fn(ctx) if step.action_context_fn else {})

        if step.step_type == "lifecycle":
            _fire_lifecycle(step, ctx)
            update_close_progress(ctx.workspace, step.name, "done")
            ctx.steps_executed.append(step.name)
            continue

    return {"ACTION": "complete", "SUMMARY": "Close complete."}


def _execute_mechanical(step: StepDef, ctx: OrchestratorContext) -> dict[str, str]:
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


def _parse_landed_shas(result: dict[str, str], ctx: OrchestratorContext) -> dict[str, str]:
    if ctx.in_slot:
        raw = result.get("LANDED_SHAS", "")
        return dict(pair.split(":") for pair in raw.split(",") if ":" in pair)
    sha = result.get("LANDED_SHA", "")
    if sha:
        return {ctx.project.name: sha}
    return {}


def _yield_judgment(step: str, workspace: Path,
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

    update_close_progress(workspace, attempt_key, str(attempt))
    result = {"ACTION": step}
    result.update(context)
    return result


def _yield_user_input(step: StepDef, ctx: OrchestratorContext) -> dict[str, str]:
    context = step.action_context_fn(ctx) if step.action_context_fn else {}
    attempt_key = f"{step.name}_attempt"
    attempt = int(ctx.progress.get(attempt_key, "0")) + 1
    if attempt > MAX_JUDGMENT_RETRIES:
        return {
            "ACTION": "user_input",
            "CONTEXT": "step_failed",
            "STEP": step.name,
            "ATTEMPTS": str(MAX_JUDGMENT_RETRIES),
            "REASON": f"Validation failed after {MAX_JUDGMENT_RETRIES} attempts",
        }
    update_close_progress(ctx.workspace, attempt_key, str(attempt))
    return {"ACTION": "user_input", **context}


def _sweep_defaults() -> str:
    return ",".join(f"{s}:on" for s in SWEEP_STEPS)


def _get_sweep_selected(progress: dict[str, str]) -> set[str]:
    raw = progress.get("sweep_selected", "")
    if not raw:
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}


def main():
    args = parse_args(sys.argv[1:])
    required = ["workspace", "branch", "meta_state"]
    for key in required:
        if key not in args:
            print(f"ERROR=missing_arg ARG={key}")
            sys.exit(1)

    result = run_orchestrator(args)
    for k, v in result.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
