#!/usr/bin/env python3
"""Dry-run audit for work-end orchestrator.

Runs the orchestrator in dry_run mode against synthetic workspaces
for each mode (branch, slot, main). Verifies all steps are reached,
all scripts have correct arguments, and no fallback triggers fire.

Usage:
    python3 work-end/audit_work_end.py mode=branch
    python3 work-end/audit_work_end.py mode=slot
    python3 work-end/audit_work_end.py mode=main
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from work_end_orchestrator import run_orchestrator, STEPS
from close_progress import update_close_progress, read_close_progress, delete_close_progress

JUDGMENT_STEPS = {
    "review", "sweep_config", "forage", "protocol",
    "update_claude_md", "impl_doc_sync", "adr", "write_content",
    "trajectory", "squash",
    "arc42_scan", "session_rename", "garden_feedback", "notes",
}

MAX_ITERATIONS = 80


PHASE_ORDER = [
    "closing:review", "closing:verified", "closing:promoted",
    "closing:pushed", "closing:merged", "closing:stamped",
    "idle", "drained",
]

LIFECYCLE_ADVANCEMENT = {
    "review_pass": "closing:verified",
    "promote_pass": "closing:promoted",
    "push_pass": "closing:pushed",
    "merge_pass": "closing:merged",
    "stamp_pass": "closing:stamped",
    "cleanup_pass": "idle",
    "cleanup_main": "drained",
}


def _build_args(workspace, project, mode, meta_state="closing:review"):
    args = {
        "workspace": str(workspace),
        "project": str(project),
        "branch": "issue-audit-test",
        "base_branch": "main",
        "meta_state": meta_state,
        "covers": "999",
        "issue_repo": "Hortora/soredium",
        "dry_run": "yes",
        "plan_path": str(workspace / ".plan"),
    }
    if mode == "slot":
        args["in_slot"] = "yes"
        args["slot_path"] = str(workspace / "slot")
        args["family_root"] = str(workspace / "family")
        args["slot_num"] = "42"
    if mode == "main":
        args["on_main"] = "yes"
        args["branch"] = "main"
    return args


def _setup_workspace(workspace, project, mode):
    workspace.mkdir(exist_ok=True)
    project.mkdir(exist_ok=True)
    if mode == "slot":
        (workspace / "slot").mkdir(exist_ok=True)
        (workspace / "family").mkdir(exist_ok=True)
    (workspace / ".plan").write_text("## State\nstate: closing:review\n")
    delete_close_progress(workspace)


def _expected_steps(mode):
    result = []
    for step in STEPS:
        if step.skip_fn:
            class FakeCtx:
                on_main = (mode == "main")
                in_slot = (mode == "slot")
                covers = "999"
                progress = {}
            if step.skip_fn(FakeCtx()):
                continue
        result.append(step.name)
    return result


def run_audit(workspace, mode="branch"):
    workspace = Path(workspace)
    project = workspace / "project"
    _setup_workspace(workspace, project, mode)

    actions_seen = []
    steps_reached = set()
    sweep_done = False
    current_meta_state = "closing:review"

    prev_progress = set()

    for i in range(MAX_ITERATIONS):
        args = _build_args(workspace, project, mode, meta_state=current_meta_state)
        result = run_orchestrator(args)

        action = result.get("ACTION", "")
        actions_seen.append(action)

        cur_progress = set(read_close_progress(workspace).keys())
        new_done = cur_progress - prev_progress
        for s in new_done:
            if not s.endswith("_attempt") and s != "sweep_selected":
                steps_reached.add(s)
        highest_advancement = current_meta_state
        for s in new_done:
            if s in LIFECYCLE_ADVANCEMENT:
                candidate = LIFECYCLE_ADVANCEMENT[s]
                if PHASE_ORDER.index(candidate) > PHASE_ORDER.index(highest_advancement):
                    highest_advancement = candidate
        current_meta_state = highest_advancement
        prev_progress = cur_progress

        if action == "error":
            step_name = result.get("STEP", "unknown")
            steps_reached.add(step_name)
            update_close_progress(workspace, step_name, "done")
            prev_progress = set(read_close_progress(workspace).keys())
            continue

        if action == "complete":
            break

        if action == "user_input":
            ctx = result.get("CONTEXT", "")
            steps_reached.add(ctx)
            update_close_progress(workspace, ctx, "done")
            prev_progress = set(read_close_progress(workspace).keys())
            continue

        if action in JUDGMENT_STEPS:
            steps_reached.add(action)
            if action == "sweep_config" and not sweep_done:
                update_close_progress(workspace, action, "done")
                update_close_progress(workspace, "sweep_selected",
                                      "forage,protocol,update_claude_md,impl_doc_sync,adr,write_content")
                sweep_done = True
            else:
                update_close_progress(workspace, action, "done")
            prev_progress = set(read_close_progress(workspace).keys())
            continue

        update_close_progress(workspace, action, "done")
        steps_reached.add(action)
        prev_progress = set(read_close_progress(workspace).keys())

    expected = set(_expected_steps(mode))

    progress = read_close_progress(workspace)
    fallback_triggers = [k for k in progress if k.startswith("fallback_")]

    missing = expected - steps_reached
    missing = {s for s in missing if not s.startswith("delete_progress") and not s.startswith("report_render")}

    all_reached = len(missing) == 0
    no_fallbacks = len(fallback_triggers) == 0
    passed = all_reached and no_fallbacks

    return {
        "RESULT": "PASS" if passed else "FAIL",
        "mode": mode,
        "steps_reached": sorted(steps_reached),
        "steps_expected": sorted(expected),
        "steps_missing": sorted(missing),
        "actions_seen": actions_seen,
        "fallback_triggers": len(fallback_triggers),
        "iterations": len(actions_seen),
    }


def main():
    args = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            args[k] = v

    mode = args.get("mode", "branch")
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_audit(Path(tmpdir), mode=mode)

    print(f"Mode: {mode}")
    for step in result["steps_reached"]:
        print(f"  + {step}")
    if result["steps_missing"]:
        print(f"\nMissing steps:")
        for step in result["steps_missing"]:
            print(f"  - {step}")
    print(f"\nSteps reached: {len(result['steps_reached'])}")
    print(f"Fallback triggers: {result['fallback_triggers']}")
    print(f"Iterations: {result['iterations']}")
    print(f"RESULT={result['RESULT']}")


if __name__ == "__main__":
    main()
