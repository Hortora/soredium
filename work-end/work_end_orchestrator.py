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
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from close_progress import (
    read_close_progress,
    update_close_progress,
    write_close_progress,
    delete_close_progress,
    is_stale,
)

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

    def done(self, step: str) -> bool:
        return self.progress.get(step) in ("done", "skipped")


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


def _skip_on_main(ctx: OrchestratorContext) -> bool:
    return ctx.on_main


def _skip_not_slot(ctx: OrchestratorContext) -> bool:
    return not ctx.in_slot


def _skip_no_covers(ctx: OrchestratorContext) -> bool:
    return not ctx.covers


def _is_sweep_deselected(step_name: str):
    def check(ctx: OrchestratorContext) -> bool:
        selected = _get_sweep_selected(ctx.progress)
        return step_name not in selected
    return check


SLOT_MANAGER = Path(__file__).parent.parent / "work-slot" / "slot_manager.py"
LIFECYCLE_SCRIPT = Path(__file__).parent.parent / "project" / "lifecycle.py"
VERIFY_SCRIPT = WORK_END_DIR / "verify_slot_close.py"
CLEANUP_SCRIPT = WORK_END_DIR / "branch_cleanup.py"


def _rebase_script(ctx):
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "rebase", f"project={ctx.project}", f"branch={ctx.branch}",
            f"base_branch={ctx.base_branch}"]


def _land_script(ctx):
    if ctx.in_slot:
        return [sys.executable, str(SLOT_MANAGER),
                "merge-slot", str(ctx.slot_path)]
    if ctx.on_main:
        return None
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "land", f"project={ctx.project}", f"branch={ctx.branch}",
            f"base_branch={ctx.base_branch}", f"workspace={ctx.workspace}"]


def _close_issues_script(ctx):
    return [sys.executable, str(WORK_END_DIR / "work_end_execute.py"),
            "close-issues", f"repo={ctx.issue_repo}", f"covers={ctx.covers}"]


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


def _push_main_mode(ctx):
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


EVIDENCE_CHECKS: dict[str, Callable] = {
    "land": lambda ws, proj: (ws / ".execute-progress").exists(),
    "rebase": lambda ws, proj: True,
    "close_issues": lambda ws, proj: True,
    "verify": lambda ws, proj: True,
    "cleanup": lambda ws, proj: True,
    "checkout_main": lambda ws, proj: True,
    "cleanup_stack": lambda ws, proj: True,
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


STEPS: list[StepDef] = [
    # --- closing:review ---
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

    # --- closing:promoted ---
    StepDef("trajectory", "closing:promoted", "judgment",
            action_context_fn=lambda ctx: {"COVERS": ctx.covers, "OWNER_REPO": ctx.issue_repo}),
    StepDef("rebase", "closing:promoted", "mechanical",
            skip_fn=_skip_on_main,
            script_fn=_rebase_script),
    StepDef("squash", "closing:promoted", "judgment",
            skip_fn=_skip_on_main,
            action_context_fn=lambda ctx: {"REPOS": ctx.project.name}),
    StepDef("land", "closing:promoted", "mechanical",
            script_fn=_land_script),

    # --- closing:stamped ---
    StepDef("close_issues", "closing:stamped", "mechanical",
            skip_fn=_skip_no_covers,
            script_fn=_close_issues_script),
    StepDef("verify", "closing:stamped", "mechanical",
            script_fn=_verify_script),
    StepDef("arc42_scan", "closing:stamped", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "arc42_scan"}),
    StepDef("session_rename", "closing:stamped", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "session_rename"}),
    StepDef("garden_feedback", "closing:stamped", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "garden_feedback"}),
    StepDef("notes", "closing:stamped", "judgment",
            action_context_fn=lambda ctx: {"CONTEXT": "notes"}),
    StepDef("cleanup", "closing:stamped", "mechanical",
            script_fn=_cleanup_scaffold_script),
    StepDef("checkout_main", "closing:stamped", "mechanical",
            skip_fn=_skip_on_main,
            script_fn=_checkout_main_script),
    StepDef("cleanup_stack", "closing:stamped", "mechanical",
            skip_fn=_skip_on_main,
            script_fn=_cleanup_stack_script),
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

    ctx = OrchestratorContext(
        workspace=workspace, project=project, branch=branch,
        base_branch=base_branch, meta_state=meta_state,
        on_main=on_main, in_slot=in_slot, covers=covers,
        issue_repo=issue_repo, progress=progress,
        dry_run=dry_run, call_log=[],
        plan_path=plan_path, slot_path=slot_path,
        family_root=family_root, slot_num=slot_num,
        expected_state=meta_state,
    )

    return _next_action(ctx)


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
            result = _execute_mechanical(step, ctx)
            if result and "ERROR" in result:
                return {"ACTION": "error", "STEP": step.name, **result}
            ctx.last_output = result or {}
            if step.name == "land":
                ctx.landed_shas = _parse_landed_shas(ctx.last_output, ctx)
            update_close_progress(ctx.workspace, step.name, "done")
            continue

        if step.step_type == "judgment":
            if step.name in ("arc42_scan", "session_rename", "garden_feedback", "notes"):
                return _yield_user_input(step, ctx)
            return _yield_judgment(step.name, ctx.workspace, ctx.progress,
                                   step.action_context_fn(ctx) if step.action_context_fn else {})

    return {"ACTION": "complete", "SUMMARY": "Close complete."}


def _execute_mechanical(step: StepDef, ctx: OrchestratorContext) -> dict[str, str]:
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
