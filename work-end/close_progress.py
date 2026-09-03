#!/usr/bin/env python3
"""Progress tracking for work-end close sequence.

Atomic write-then-rename. Stale detection via lifecycle state comparison.
"""
import os
import sys
from pathlib import Path

_project_dir = Path(__file__).resolve().parent.parent / "project"
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))
from plan_io import read_field as _read_plan_field

PROGRESS_FILE = ".close-progress"
PROGRESS_TMP = ".close-progress.tmp"

LIFECYCLE_PHASE_ORDER = [
    "active",
    "closing:review",
    "closing:verified",
    "closing:promoted",
    "closing:pushed",
    "closing:merged",
    "closing:stamped",
    "idle",
    "drained",
]

STEP_TO_PHASE = {
    "report_init": "closing:review",
    "review": "closing:review",
    "code_review": "closing:review",
    "branch_audit_conformance": "closing:review",
    "branch_audit_coherence": "closing:review",
    "branch_audit_structure": "closing:review",
    "branch_audit_robustness": "closing:review",
    "loose_ends": "closing:review",
    "forcing_function": "closing:review",
    "sweep_config": "closing:review",
    "forage": "closing:review",
    "protocol": "closing:review",
    "update_claude_md": "closing:review",
    "impl_doc_sync": "closing:review",
    "doc_freshness_gate": "closing:review",
    "adr": "closing:review",
    "write_content": "closing:review",
    "promote": "closing:verified",
    "report_promote": "closing:verified",
    "trajectory": "closing:promoted",
    "rebase": "closing:promoted",
    "report_rebase": "closing:promoted",
    "squash": "closing:promoted",
    "report_squash": "closing:promoted",
    "write_marker": "closing:promoted",
    "land": "closing:promoted",
    "report_land": "closing:promoted",
    "close_issues": "closing:stamped",
    "report_close_issues": "closing:stamped",
    "verify": "closing:stamped",
    "report_verify": "closing:stamped",
    "archive_slot": "closing:stamped",
    "report_archive": "closing:stamped",
    "checkout_main": "closing:stamped",
    "cleanup_stack": "closing:stamped",
    "cleanup": "closing:stamped",
    "report_scaffold": "closing:stamped",
    "upstream_pr": "closing:stamped",
    "arc42_scan": "closing:stamped",
    "session_rename": "closing:stamped",
    "garden_feedback": "closing:stamped",
    "notes": "closing:stamped",
    "delete_progress": "idle",
    "report_render": "idle",
}


def read_close_progress(workspace: Path) -> dict[str, str]:
    path = workspace / PROGRESS_FILE
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def write_close_progress(workspace: Path, entries: dict[str, str]) -> None:
    path = workspace / PROGRESS_FILE
    tmp = workspace / PROGRESS_TMP
    lines = [f"{k}={v}" for k, v in entries.items()]
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, path)


def update_close_progress(workspace: Path, key: str, value: str) -> None:
    entries = read_close_progress(workspace)
    entries[key] = value
    write_close_progress(workspace, entries)


def delete_close_progress(workspace: Path) -> None:
    for name in (PROGRESS_FILE, PROGRESS_TMP):
        p = workspace / name
        if p.exists():
            p.unlink()


def _read_plan_state(plan_path: Path) -> str:
    """Read the lifecycle state from a .plan file."""
    return _read_plan_field(plan_path, "state") or ""


def is_stale(progress: dict[str, str], meta_state: str,
             plan_path: Path | None = None) -> bool:
    if not progress:
        return False
    if plan_path and plan_path.exists():
        actual_state = _read_plan_state(plan_path)
        if actual_state and actual_state in LIFECYCLE_PHASE_ORDER:
            meta_state = actual_state
    if meta_state not in LIFECYCLE_PHASE_ORDER:
        return False
    meta_idx = LIFECYCLE_PHASE_ORDER.index(meta_state)
    max_progress_idx = 0
    for step in progress:
        base_step = step.split("_attempt")[0] if "_attempt" in step else step
        phase = STEP_TO_PHASE.get(base_step, "closing:review")
        if phase in LIFECYCLE_PHASE_ORDER:
            idx = LIFECYCLE_PHASE_ORDER.index(phase)
            max_progress_idx = max(max_progress_idx, idx)
    return max_progress_idx > meta_idx
