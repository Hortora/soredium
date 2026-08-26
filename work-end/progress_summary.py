#!/usr/bin/env python3
"""
progress_summary.py — Mechanical step-status report for close and wrap sequences.

Reads .close-progress and outputs a deterministic summary.
The LLM prints this verbatim — it does not compose its own summary.

Usage:
    python3 work-end/progress_summary.py <workspace> [mode=close|wrap]
"""

import json
import sys
from pathlib import Path

_work_end = Path(__file__).resolve().parent
sys.path.insert(0, str(_work_end))

from close_progress import read_close_progress


CLOSE_VISIBLE_STEPS = [
    ("code_review", "Code review"),
    ("branch_audit_conformance", "Conformance"),
    ("branch_audit_coherence", "Coherence"),
    ("branch_audit_structure", "Structure"),
    ("branch_audit_robustness", "Robustness"),
    ("loose_ends", "Loose ends"),
    ("forcing_function", "Forcing function"),
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

REVIEW_STEPS = {
    "code_review", "branch_audit_conformance", "branch_audit_coherence",
    "branch_audit_structure", "branch_audit_robustness",
    "loose_ends", "forcing_function",
}

DIMENSION_MAP = {
    "branch_audit_conformance": "conformance",
    "branch_audit_coherence": "coherence",
    "branch_audit_structure": "structure",
    "branch_audit_robustness": "robustness",
}


def _read_findings(workspace: Path) -> list[dict]:
    path = workspace / ".audit" / "findings.jsonl"
    if not path.exists():
        return []
    findings = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            findings.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            pass
    return findings


def _findings_by_source(findings: list[dict]) -> dict[str, list[dict]]:
    by_source: dict[str, list[dict]] = {}
    for f in findings:
        source = f.get("source", "unknown")
        by_source.setdefault(source, []).append(f)
    return by_source


def _findings_by_dimension(findings: list[dict]) -> dict[str, list[dict]]:
    by_dim: dict[str, list[dict]] = {}
    for f in findings:
        dim = f.get("dimension", "")
        if dim:
            by_dim.setdefault(dim, []).append(f)
    return by_dim


def _resolution_summary(findings: list[dict]) -> str:
    fixed = sum(1 for f in findings if f.get("status") == "resolved")
    filed = sum(1 for f in findings if f.get("status") == "filed")
    dismissed = sum(1 for f in findings if f.get("status") == "dismissed")
    still_open = sum(1 for f in findings if f.get("status", "open") == "open")
    parts = []
    if fixed:
        parts.append(f"{fixed} fixed")
    if filed:
        parts.append(f"{filed} filed")
    if dismissed:
        parts.append(f"{dismissed} dismissed")
    if still_open:
        parts.append(f"{still_open} OPEN")
    return ", ".join(parts) if parts else "0 findings"


def _finding_line(f: dict) -> str:
    sev = f.get("severity", "warning").upper()
    source = f.get("source", "")
    detail = f.get("detail", "")[:80]
    status = f.get("status", "open")
    resolution = f.get("resolution", "")
    loc = f.get("location", "")
    loc_str = f" {loc}" if loc else ""

    if status == "resolved":
        outcome = f"fixed ({resolution})" if resolution else "fixed"
    elif status == "filed":
        outcome = f"filed ({resolution})" if resolution else "filed"
    elif status == "dismissed":
        outcome = f"dismissed ({resolution})" if resolution else "dismissed"
    else:
        outcome = "OPEN"

    return f"       [{sev}] {source}{loc_str}: {detail} → {outcome}"


def _sweep_detail(step_name: str, progress: dict[str, str], sweep_key: str, sweep_steps: set[str]) -> str:
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


def _review_step_detail(step_name: str, progress: dict[str, str],
                        findings: list[dict]) -> str:
    produced = progress.get(f"{step_name}_produced", "")

    if step_name == "code_review":
        by_source = _findings_by_source(findings)
        code_findings = by_source.get("code-review", [])
        count = int(produced) if produced else len(code_findings)
        return f"{count} finding{'s' if count != 1 else ''}" if count else "clean"

    if step_name in DIMENSION_MAP:
        dim = DIMENSION_MAP[step_name]
        by_dim = _findings_by_dimension(findings)
        dim_findings = by_dim.get(dim, [])
        count = int(produced) if produced else len(dim_findings)
        return f"{count} finding{'s' if count != 1 else ''}" if count else "clean"

    if step_name == "loose_ends":
        by_source = _findings_by_source(findings)
        le_findings = by_source.get("loose-ends-sweep", [])
        count = int(produced) if produced else len(le_findings)
        return f"{count} finding{'s' if count != 1 else ''}" if count else "clean"

    if step_name == "forcing_function":
        return _resolution_summary(findings)

    return produced if produced else ""


def format_summary(progress: dict[str, str], mode: str = "close",
                   workspace: Path | None = None) -> str:
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

    findings = _read_findings(workspace) if workspace else []

    lines = [title, "─" * len(title)]

    for step_name, label in visible:
        status = progress.get(step_name, "")

        if status == "done":
            icon = "✅"
            if step_name in REVIEW_STEPS:
                detail = _review_step_detail(step_name, progress, findings)
            elif step_name in ("sweep_config", "wrap_sweep_config"):
                detail = _sweep_config_detail(progress, sweep_key)
            else:
                detail = _produced_detail(step_name, progress)
        elif status == "skipped":
            icon = "⏭"
            detail = _sweep_detail(step_name, progress, sweep_key, sweep_steps) or "skipped"
        else:
            icon = "⬜"
            detail = "not reached"

        suffix = f" — {detail}" if detail else ""
        lines.append(f"  {icon} {label:<20s}{suffix}")

    if findings and mode == "close":
        lines.append("")
        lines.append("  Findings:")
        for f in findings:
            lines.append(_finding_line(f))

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

    print(format_summary(progress, mode, workspace=workspace))


if __name__ == "__main__":
    main()
