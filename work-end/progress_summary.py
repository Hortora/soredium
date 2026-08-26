#!/usr/bin/env python3
"""
progress_summary.py — Mechanical step-status report for close and wrap sequences.

Reads .close-progress and outputs a deterministic summary.
The LLM prints this verbatim — it does not compose its own summary.

Usage:
    python3 work-end/progress_summary.py <workspace> [mode=close|wrap]
"""

import sys
from pathlib import Path

_work_end = Path(__file__).resolve().parent
sys.path.insert(0, str(_work_end))

from close_progress import read_close_progress


CLOSE_VISIBLE_STEPS = [
    ("review", "Review"),
    ("sweep_config", "Sweep config"),
    ("forage", "Forage SWEEP"),
    ("protocol", "Protocol SWEEP"),
    ("update_claude_md", "CLAUDE.md sync"),
    ("impl_doc_sync", "Doc sync"),
    ("adr", "ADR"),
    ("write_content", "Diary entry"),
    ("promote", "Promote artifacts"),
    ("trajectory", "Trajectory"),
    ("rebase", "Rebase"),
    ("squash", "Squash"),
    ("land", "Land"),
    ("close_issues", "Close issues"),
    ("verify", "Verify"),
    ("arc42_scan", "ARC42 scan"),
    ("session_rename", "Session rename"),
    ("garden_feedback", "Garden feedback"),
    ("notes", "Notes"),
]

WRAP_VISIBLE_STEPS = [
    ("loose_ends", "Loose ends"),
    ("epic_hygiene", "Epic hygiene"),
    ("wrap_sweep_config", "Sweep config"),
    ("forage", "Forage SWEEP"),
    ("protocol", "Protocol SWEEP"),
    ("update_claude_md", "CLAUDE.md sync"),
    ("journal_entry", "Journal entry"),
    ("arc42_scan_wrap", "ARC42 scan"),
    ("write_content", "Diary entry"),
    ("garden_feedback", "Garden feedback"),
    ("notes", "Notes"),
    ("handoff_write", "HANDOFF.md"),
    ("wip_commit", "WIP commit"),
]

CLOSE_SWEEP_STEPS = {"forage", "protocol", "update_claude_md", "impl_doc_sync", "adr", "write_content"}
WRAP_SWEEP_STEPS = {"forage", "protocol", "update_claude_md", "write_content"}


def _sweep_detail(step_name: str, progress: dict[str, str], sweep_key: str, sweep_steps: set[str]) -> str:
    """Determine why a sweep step was skipped: deselected vs auto-skipped."""
    if step_name not in sweep_steps:
        return ""
    selected_raw = progress.get(sweep_key, "")
    if not selected_raw and sweep_key not in progress:
        return "not configured"
    selected = {s.strip() for s in selected_raw.split(",") if s.strip()}
    if step_name not in selected:
        return "deselected"
    return ""


def _produced_detail(step_name: str, progress: dict[str, str]) -> str:
    produced = progress.get(f"{step_name}_produced", "")
    if produced and produced != "0":
        return f"{produced} produced"
    return ""


def _sweep_config_detail(progress: dict[str, str], sweep_key: str) -> str:
    raw = progress.get(sweep_key, "")
    if not raw:
        return "none selected"
    items = [s.strip() for s in raw.split(",") if s.strip()]
    return ", ".join(items)


def format_summary(progress: dict[str, str], mode: str = "close") -> str:
    if mode == "wrap":
        visible = WRAP_VISIBLE_STEPS
        sweep_key = "wrap_sweep_selected"
        sweep_steps = WRAP_SWEEP_STEPS
        title = "Wrap summary"
    else:
        visible = CLOSE_VISIBLE_STEPS
        sweep_key = "sweep_selected"
        sweep_steps = CLOSE_SWEEP_STEPS
        title = "Close summary"

    lines = [title, "─" * len(title)]

    for step_name, label in visible:
        status = progress.get(step_name, "")

        if status == "done":
            icon = "✅"
            detail = _produced_detail(step_name, progress)
            if step_name in ("sweep_config", "wrap_sweep_config"):
                detail = _sweep_config_detail(progress, sweep_key)
        elif status == "skipped":
            icon = "⏭"
            detail = _sweep_detail(step_name, progress, sweep_key, sweep_steps) or "skipped"
        else:
            icon = "⬜"
            detail = "not reached"

        suffix = f" — {detail}" if detail else ""
        lines.append(f"  {icon} {label:<20s}{suffix}")

    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    workspace = Path(sys.argv[1])
    mode = "close"
    for arg in sys.argv[2:]:
        if arg.startswith("mode="):
            mode = arg.split("=", 1)[1]

    done_path = workspace / ".close-progress.done"
    if done_path.exists():
        progress = {}
        for line in done_path.read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                progress[k.strip()] = v.strip()
    else:
        progress = read_close_progress(workspace)

    if not progress:
        print("NO_PROGRESS=true")
        sys.exit(0)

    print(format_summary(progress, mode))


if __name__ == "__main__":
    main()
